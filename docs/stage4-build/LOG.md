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
