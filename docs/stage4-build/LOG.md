# Agent Central: Stage 4 build run log

Branch: `stage2-legibility` (continuing, not branching, not merging). No em-dashes.

Two parts: (1) no-spend visual fixes (server with ANTHROPIC_API_KEY unset), then
(2) a small, HARD-CAPPED live run that spends real money to repopulate the data.

## Spend caps (inviolable, enforced in code)
- Cheapest model only: claude-haiku-4-5.
- Hard caps for the whole live run, whichever hits first stops it:
  - total spend ceiling ~$1.00
  - total LLM call ceiling: target ~40 successful, hard cap 60 calls
  - wall-clock ~15 minutes
- F4 backoff stays: failing calls pause, never loop.
- A SpendGuard counter stops the analyst before each call once any cap is reached,
  and it is unit-tested + dry-verified before any real spend.

## Progress

### P1.1 removed redundant LIVE METRICS terminal
Removed the in-world terminal pill (HTML element, CSS, and its click handler). The
upper-floor Control screens still open the same metrics dashboard via the canvas
hitControl click path. Verified: terminal element is gone, and a synthetic click on
the Control screens opens the dashboard. Screenshot: p1-1-terminal-removed.png.

### P1.2 dismissible offline banner
Added a clear (x) close control to the offline/reconnecting banner. Dismissal is
keyed on a signature of the exact condition (which agents are offline, or
"reconnecting"): a dismissed signature stays closed across polls, but a genuinely
new condition (a different agent going offline, or the set changing) shows it
again. Verified: the banner shows a close button, and after dismissing it stays
hidden across a 4s poll cycle. Screenshot: p1-2-banner.png.

### P1.3 bottom label overlap + P1.4 replay pill collision
P1.4: moved the replay pill from the bottom-right corner (where it sat over the
activity ticker / Windows-watermark area) to the right rail just below the jobs
funnel (top:244, right:14), so it is fully readable and clear of the ticker and
corner at common window sizes.
P1.3: strengthened the name-label layout: added a 7px horizontal gap to the
overlap test (so adjacent labels like "Job Analyst"/"Secretary" stagger onto their
own rows instead of touching) and clamped each label box to stay within the canvas
so crowded bottom-edge labels never run off the edge or into the corner. Verified
by clustering all four agents in the Lounge: labels stack into four clean,
readable rows and stay on-canvas. Screenshots: p1-3-labels-after.png, p1-34-after.png.

## Phase 2: data refresh (HARD-CAPPED real spend)

### SpendGuard (built + verified BEFORE any spend)
Added job_analyst.SpendGuard(max_calls, max_cost_usd, max_seconds): allow() is
checked before every call and returns False (recording which cap) once any cap is
hit; record() accrues calls + estimated cost. process_pending_jobs takes an
optional guard and stops the loop before any call that would breach a cap.
Unit-tested: each cap triggers; a guard with 0 allowed calls makes ZERO real
calls; a cap of 2 stops after exactly 2. Full suite: 110 passing.

### Archive + fresh DB
Archived the old data DB (mostly historical credit-failure data) to
data/activity-archive-20260604-215010.db (verified: 4729 llm_calls rows,
non-empty), then started the agents against a fresh empty data/activity.db. Both
the DB and the archive are gitignored and never committed.

### Live run results (EXACT spend)
- Job Scout discovery (FREE, no LLM): fetched 116 jobs, stored 86 pending to score.
- Capped analyst scoring (claude-haiku-4-5) under SpendGuard(max_calls=60,
  max_cost_usd=$1.00, max_seconds=900): stopped at the 40-successful-score target.
  EXACT spend: 40 real calls, 0 errors, $0.0797 (guard.cost 0.079687). No hard cap
  was hit (the target stop fired first; well under 60 calls / $1.00 / 15 min).
- Then ran 4 additional FREE Job Scout passes (no LLM) to enrich real activity.

### Before / after success rate
- BEFORE: 137 ok / 4729 calls = 2.9% success (old credit-failure data).
- AFTER: 40 ok / 40 calls = 100.0% success. 58,889 tokens (48,709 in / 10,180 out),
  $0.0797 spend, avg latency ~3.7s. Jobs funnel: 86 found, 30 filter-rejected,
  39 LLM-rejected, 1 scored (72), 46 still pending. Real state durations.
  The dashboard "LLM calls / day" chart is now all-green (success) instead of red.

### Phase 3: fresh demo on the healthy data
Re-captured on the refreshed data: s4-dashboard.png (100% success), s4-office.png,
s4-replay.png. Rebuilt the hero GIF (docs/stage4-build/hero-demo.gif, 29 frames,
~2.3MB: live office -> healthy dashboard -> replay of the real day) and README
stills (readme-cold-open/office/dashboard/replay/secretary.png). Pointed the README
hero at the new asset. Added slower replay speeds (30x/120x default) so the short
fresh recorded day is watchable on auto-play. README claims kept honest (the live
demo server runs keyless, so the HUD honestly shows the analyst paused; the
dashboard + replay show the healthy recorded run).
