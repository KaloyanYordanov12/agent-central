# Agent Central: Stage 3 build run log

Branch: `stage2-legibility` (continuing, not branching, not merging). Zero real API
calls: every server run uses ANTHROPIC_API_KEY unset so the Job Analyst pauses (F4)
and spends nothing. No em-dashes in this log.

## Roadmap (build in this order, one at a time)

Phase 1, warm-up bug fixes:
1. Top-bar collision: stop the offline banner and the LLM cost ticker overlapping.
2. Agent name-label overlap: keep adjacent agents' labels legible.

Phase 2, main work (full creative ownership, cohesion is the hard constraint):
- A. Unify the popup/panel system.
- B. Clickable in-world terminal that opens a real metrics dashboard (read-only
     observability over llm_calls + activity_log). Add endpoints + tests.
- C. Clearly-labeled REPLAY mode driving the office from real recorded events,
     with a timeline scrubber, play/pause/speed, and a persistent REPLAY badge.
- D. Ambient polish (lit windows, day/night tint, building frame/marquee), tasteful.

Phase 3: full backend regression (was 101 green) + confirm all Stage 2 features.
Phase 4: capture hero demo + polished README stills under docs/stage3-build/.

## Design decision (cohesion)

I own the look this run. The hard constraint is cohesion, and there were two
clashing popup languages: warm parchment cards, and large navy-header / cream-body
modals. My decision is a DELIBERATE TWO-TIER system, split by meaning:

- Tier 1, "console" (dark charcoal, amber accents, JetBrains Mono): every surface
  that shows real system data. This matches the always-on HUD, ticker, jobs funnel
  and cost ticker from Stage 2. The Secretary / Job Scout / Job Analyst modals and
  the new metrics dashboard all move into this language. This is the observability
  identity of the piece.
- Tier 2, "parchment" (warm cream, brown border, wax-seal close): kept only for
  in-world flavor and character lore (the aquarium, the nap couch, the archives,
  Deal Hunter's profile). These read as NPC dialogue, deliberately unlike the data
  panels.

So the rule a viewer can feel: warm parchment = playful in-world lore; dark console
= real telemetry. The pixel-art office stays the hero; all UI is dark, translucent,
and out of the way so it never buries the world.

## Progress

### P1.1 top-bar collision fixed
The offline banner (top-center) overlapped the LLM cost ticker (anchored to the
building's top-right). Fix: moved the cost ticker out of the building into a fixed
top-right console chip, stacked the jobs funnel below it (top:66 leaves a 10px
gap), and constrained the banner to a center lane (max-width min(560px,
calc(100vw - 540px))) so it can never reach the left HUD or the right stack at any
common width. Verified: banner right 954, cost left 1116 (162px clear); cost/funnel
gap 10px. Screenshot: p1-topbar-fixed.png.

### P1.2 agent name-label overlap fixed
Name labels collided when agents stood close. Fix: collision-aware label layout in
render() that, after sorting by depth, stacks each label upward (3px gap) until it
clears any already-placed label whose box it would overlap. Added drawLabelAt() for
explicit positioning and a window.__freeze hook (also used by replay) for
deterministic capture. Verified by forcing three agents onto one spot: labels
"Deal Hunter / Job Scout / Job Analyst" stagger and stay legible.
Screenshot: p1-labels-staggered.png.

### Phase 2A: unified popup system (two-tier, cohesive)
Resolved the two clashing popup languages into a DELIBERATE two-tier system split
by meaning. Tier 1 "console" (dark charcoal #0e1118, amber accents, JetBrains Mono)
now styles every data modal (Secretary, Job Scout, Job Analyst, and the upcoming
dashboard); it matches the always-on HUD, ticker, funnel and cost chip. Tier 2
"parchment" (the existing warm .popup) is kept only for in-world flavor objects and
Deal Hunter's lore. This was a CSS-only change to the .secretary-popup family and
its inner content (history items, ask panel, score badges, paused/empty notices),
recolored to the dark palette; the parchment .popup tier was left untouched. The
split is intentional and obvious: dark = real telemetry, parchment = playful lore.
Screenshots: f2a-secretary.png, f2a-analyst.png (dark console), f2a-flavor.png,
f2a-dealhunter.png (parchment).

### Phase 2B: in-world terminal + real metrics dashboard
Backend: new read-only metrics module (agent_central/metrics.py) + GET /api/metrics
aggregating llm_calls and activity_log into totals, success rate, tokens, cost, avg
latency, per-model and per-agent breakdowns, per-day call/token series, activity
event counts, and per-agent state durations (computed from consecutive
state_change gaps). 5 new tests (test_metrics.py); full suite 106 passing.
Frontend: a discoverable, pulsing in-world "LIVE METRICS" terminal pill anchored
over the Control desks (and the Control screens themselves) opens a Tier 1 console
dashboard with inline SVG charts (no chart library): KPI tiles, LLM-calls/day and
tokens/day stacked bars, by-model and by-agent tables, and time-in-state bars.
This supersedes the old hidden parchment "Control stats" hotspot. Verified live
with real data (4,724 calls, 2.8% success, 171,474 tokens, state durations).
Screenshots: f2b-terminal.png, f2b-dashboard-zoom.png.

### Phase 2C: REPLAY mode (honest by construction)
Backend: activity_log.get_replay_timeline + GET /api/replay/timeline returns the
ordered (oldest-first) real state-bearing events for the last N days as compact
{timestamp, agent_id, state} rows. 1 new test (870 real events live).
Frontend: a "Replay the recorded day" pill enters replay; a control bar shows a
persistent pulsing red REPLAY badge, the exact replayed timestamp, play/pause, a
speed selector (500x/2000x/8000x) and a draggable scrubber. A replay clock advances
the replayed time and applies, per agent, the latest recorded state at that moment
via setBackendState, so the existing walking sim re-enacts the day. Honesty +
clean separation: while window.__replayActive the live WS handler ignores live
messages; replay only ever plays REAL recorded states (never fabricated); Exit
returns to live. Verified: scrubbing moves the replayed clock across 2026-06-03/04
and the office re-enacts. Screenshots: f2c-replay.png, f2c-replay-bar.png.

### Phase 2D: ambient polish (tasteful, low-risk)
Restyled the building marquee into a mounted "AGENT CENTRAL" plate (console palette,
amber border + text + corner bolts) and made it actually visible at the roofline;
moved the offline banner down to 52px so the two never collide. Grounded the
building with a soft drop shadow. Added a day/night tint: a low-alpha overlay over
the world (z-index below all UI) tied to the real local clock (night/dawn/midday/
golden-hour/dusk), so the scene subtly reflects the time without hurting the Stage 2
legibility. No canvas-internals or building-rescale changes (B1 stays out of scope).
Screenshots: f2d-full.png, f2d-marquee.png.

### Phase 3: full regression pass
Backend suite: 107 passing (101 from Stage 2 + 6 new metrics/replay tests). Loaded
the app and confirmed every Stage 2 legibility feature still works in the new
cohesive dark theme with no collisions: status HUD, live activity ticker, jobs
funnel, room labels + zone legend, honest cost ticker, offline banner, cold-open
onboarding, and the F3 empty/paused states (Ask empty state re-themed cleanly).
The office still renders and animates. Screenshots: p3-composed.png, p3-ask-empty.png.
