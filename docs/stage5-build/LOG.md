# Agent Central: Stage 5 build run log

Branch: `stage2-legibility` (not merged). No spend: the server ran with
ANTHROPIC_API_KEY unset (the Job Analyst paused via F4); this session made zero
real API calls. No em-dashes in this log.

## Goal: remove the REPLAY feature entirely

### Removed
Frontend (`agent_central/static/index.html`):
- The "Replay the recorded day" pill (#replay-pill) and the replay control bar
  (#replay-bar: REPLAY badge, #rp-time, #rp-play, #rp-speed, #rp-scrub, #rp-exit),
  plus all their CSS (.replay-pill, .replay-bar, .rp-badge, .rp-dot, .rp-time,
  .rp-btn, .rp-speed, #rp-scrub).
- The entire replay engine script (the IIFE that fetched /api/replay/timeline and
  set window.__replayActive / __enterReplay / __exitReplay).
- The `if(window.__replayActive) return;` guard in the WebSocket onmessage handler,
  so live WS state is always applied again (the office is purely live).
- Tidied two comments that referenced replay. Kept window.__freeze and
  window.AGENTS_SIM / window.NODE_POS: they are debug hooks used for deterministic
  screenshots / label-layout checks, not by replay, so they stay.

Backend:
- Removed GET /api/replay/timeline from `agent_central/api.py`.
- Removed get_replay_timeline from `agent_central/activity_log.py`.
- Removed the test test_replay_timeline_ordered_state_events_only from
  `tests/test_metrics.py`.

Docs:
- README: removed REPLAY from the hero caption, the feature bullets, the Demo
  paragraph, and "What works"; also corrected the now-stale "in-world LIVE METRICS
  terminal" wording (that terminal was removed in Stage 4) to "the Control
  screens", which is how the dashboard is opened.

### Hero GIF
Regenerated a fresh hero GIF WITHOUT the replay segment: live office -> metrics
dashboard (opened by clicking the Control screens) -> back to office. Saved to
docs/stage5-build/hero-demo.gif (20 frames, ~1.4MB) and pointed the README hero at
it. Fresh stills: readme-office.png, readme-dashboard.png. (Older stage3/stage4
hero GIFs are left in place as historical artifacts but are no longer referenced.)

### Verification
- Full backend suite: 109 passing (was 110; removed the one replay test).
- Repo grep: no replay references remain in source, tests, or README. Replay is
  only mentioned in the historical run LOGs (docs/stage2..4-build) and the Stage 1
  IMPROVEMENTS.md proposal, which are historical records and left as-is.
- Live UI check (CDP, key-unset server): replay pill and bar are gone,
  window.__replayActive / __enterReplay are undefined, and NO JS console errors.
  All other features still work: status HUD (4 rows), activity ticker, jobs funnel
  (5 rows), room labels (7) + zone legend, cost chip, dismissible offline banner,
  onboarding, and the metrics dashboard opened by clicking the Control screens.
  The office renders and agents update from live WS state.

Note: the data DB grew between Stage 4 and now (40 -> 85 successful llm_calls, all
ok) from a keyed run outside this session; this session itself spent $0.00.
