# Agent Central: Stage 2 build run log

Branch: `stage2-legibility`. Scope: fix the LLM engine (F1 + F4), then the
legibility bundle (D1, A3, A2, A1, A4, D3, F2, F3). No popup/premium/wow work.

No em-dashes in this log.

## Phase 1: engine diagnosis (read-only, before any real API call)

Read `job_analyst.py` (the LLM caller) and the failed-call records in
`data/activity.db` (`llm_calls`). Findings:

- 4592 failed calls (ok=0). 4591 of them carry the identical message:
  `invalid_request_error: "Your credit balance is too low to access the
  Anthropic API."` The one other failure is a transient "Connection error."
- This is a billing/credit condition that Anthropic returns as an HTTP 400, which
  is why it superficially looked like a request bug. It is NOT a code bug.
- Proof the request shape is valid: there are 127 successful calls (ok=1) on the
  exact same code path (model `claude-haiku-4-5`, `system` with
  `cache_control {"type":"ephemeral","ttl":"1h"}`). In the 15:00 UTC hour today
  the calls transitioned from failing (60) to succeeding (35), and the last 6
  logged calls all succeeded (latest 2026-06-04T15:58:25). So credit was empty
  for most of history and has since been funded.

Conclusion: there is no request/model bug to fix. The cause was an empty
Anthropic credit balance; it is now funded. The real engineering problems are:
(F4) the analyst hammered the API with one failed call per pending job every
cycle, logging thousands of $0 failures, with no backoff; and (F1) the cost
ticker counts those failed calls as "calls" and reports $0, which reads as broken.

Plan: build F4 backoff first (so nothing can hammer the API), make exactly one
isolated real Haiku call to confirm success live, then ship the honest F1 ticker,
then the legibility bundle. All server runs for screenshots are done with
ANTHROPIC_API_KEY unset so the analyst makes zero real calls.

### F4 backoff (shipped first, so nothing can hammer the API)

- `job_analyst.py`: added `_is_fatal_config_error()` (credit balance, auth,
  permission, 401). `process_pending_jobs` now aborts the pass on the first fatal
  error (records it in `stats["fatal_error"]`, breaks the loop) instead of failing
  one call per pending job. Transient errors still behave as before (retry next
  pass). `run_analyst_pass` propagates `fatal_error`.
- `api.py` `JobAnalystTask`: added a sticky `paused` / `pause_reason`. It pauses
  (logs once, emits a `paused` lifecycle event, skips all future passes) when the
  profile is missing, the client cannot be built (no/invalid key), or a pass
  returns a fatal error. `/api/jobs/analyst-activity` now reports `paused` and
  `pause_reason`.
- Tests added: fatal-vs-transient classification, and that a fatal error aborts
  the pass after one call leaving the rest `discovered`. Full suite: 100 passed.

### Verification: exactly one real Anthropic call

Made ONE isolated minimal Haiku call (max_tokens=5, "reply ok") outside the
analyst path. Result: SUCCESS. `model=claude-haiku-4-5-20251001`, reply "ok",
14 input / 4 output tokens (about $0.00003). This live-confirms the diagnosis:
the request shape and model are valid; the only past failure cause was the empty
credit balance, which is now funded. No code change to the request was needed.

Real API calls spent: 1 (of a hard ceiling of 10). No further real calls will be
made; all server runs below use ANTHROPIC_API_KEY unset so the analyst pauses
(F4) and spends nothing.

### F1 honest cost ticker (shipped)

- `activity_log.get_costs_today` now splits successful from failed calls:
  `total_usd`, `call_count` and `by_agent`/`by_model` come from ok=1 calls only;
  failures are a separate `error_count`; added `input_tokens`/`output_tokens`.
  Failed calls (for example empty credit) used to be counted as free "calls".
- Ticker now reads e.g. `LLM today: $0.0681 (35 ok calls) - 3500 failed` and turns
  amber when there are failures. The Control live-stats popup shows spend,
  successful calls, failed calls, token in/out, and a plain-language note that
  many-failures-zero-success usually means empty credit and the analyst pauses.
- Test added (`test_llm_costs_today_counts_failures_separately`). Suite: 101 passed.
- Verified live: with real data (35 ok / 3500 failed today), ticker and popup show
  the honest split. Screenshots: `f1-01-office-ticker.png`, `f1-02-control-stats.png`.

## Phase 2: legibility bundle (no real API calls)

All server runs use ANTHROPIC_API_KEY unset, so the analyst pauses (F4) and the
office is driven purely by reads of existing activity-log / jobs data over the WS.

### D1 live activity ticker (shipped)

A fixed bottom news-crawl (`#activity-ticker`) with a pulsing red LIVE badge.
A self-contained script polls `/api/secretary/history?limit=18` every 6s and
narrates each real event into a factual, color-coded line (agent name in its
colour + verb + timestamp), e.g. "Deal Hunter went offline", "Job Analyst paused
itself (misconfigured)", "Job Scout started scanning". CSS marquee scroll, pauses
on hover, only restarts when the text actually changes. Read-only; no backend
change, so all backend tests stay green (root-serves test passes). Verified: the
ticker shows the real current events. Screenshot: `d1-ticker-zoom.png`.

### A3 always-on live status HUD (shipped)

A fixed top-left panel ("Agents - live") with one row per agent: a colored status
dot, the agent name in its colour, a human-readable state, the current action
(when working), and "updated Ns ago". It reads `window.AGENT_LIVE` (the same live
WS state that drives the office; exposed with a one-line alias) and re-renders
every second, tracking state-change times locally for the "ago" label.

Honesty fix folded in: the analyst's F4 pause is now logged as a `state_change`
(was `lifecycle`, which `get_current_state` excludes), so the HUD and office show
"Paused (misconfigured)" instead of a misleading "Idle". Verified live: HUD shows
Deal Hunter Offline, Job Scout Idle, Job Analyst Paused (misconfigured), Secretary
Idle. Full suite 101 passed. Screenshot: `a3-hud-zoom.png`.

### A2 room labels + zone legend (shipped)

Taste call from IMPROVEMENTS.md resolved the safe way: a clean HTML overlay, NOT
text baked into the locked pixel-art canvas. A small script reads the engine's
`window.ROOMS` rects and drops an unobtrusive label tab at the top-center of each
room (Control, Thinking, Library, Comms, Browse, Writing, Lounge). The labels are
children of `.building` so they track it wherever it centers, and are
`pointer-events:none` so clicks still reach the canvas. A compact bottom-left
"Zones" legend maps each room to its pipeline meaning (Browse: scanning the web,
Thinking: LLM analysis, etc.). Screenshots: `a2-full.png`, `a2-building.png`.

