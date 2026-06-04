# Agent Central: Stage 1 Research and Proposed Improvements

A read-only study of the current project and a ranked menu of improvements to
polish and deepen it into an AI-portfolio centerpiece. Nothing here is built yet.
This document is a menu for you to greenlight (whole groups or single items)
before a separate build run executes it feature by feature.

Reference screenshots live in `docs/stage1-research/` and are captured from the
app running locally on port 8001 (Agent Central only; Deal Hunter on port 8000
was not running, which is itself informative, see Group F).

- `01-office-overview.png` ......... the full page as a cold viewer first sees it
- `09-building-closeup.png` ........ crisp 2x zoom of the building (best detail view)
- `02-control-live-stats.png` ...... the live LLM-cost popup (click the monitors)
- `03-deal-hunter-popup.png` ....... Deal Hunter parchment info popup
- `04-flavor-aquarium.png` ......... a furniture flavor popup (the Larry-the-fish easter egg)
- `05-secretary-history.png` ....... Secretary modal, History tab
- `06-secretary-ask.png` ........... Secretary modal, Ask tab (empty state)
- `07-job-scout.png` ............... Job Scout modal, Recent Discoveries
- `08-job-analyst.png` ............. Job Analyst modal, Recent Scores

---

## 1. Current state: what it is and what works today

Agent Central is a single-page pixel-art office (a 360x348 canvas drawn at 2x)
set against a painted sky / lawn / city background. Seven rooms (Control,
Thinking, Library, Comms, Browse, Writing, Lounge) are stacked across floors and
joined by staircases. Four agent characters (Deal Hunter, Job Scout, Job Analyst,
Secretary) walk a node graph with real pathfinding, sit at desks to "work,"
roam when idle, greet each other on proximity, and dim when offline. The whole
thing is driven by a real FastAPI + WebSocket backend: a 1.5s poller reads Deal
Hunter's `/status` and derives the other three agents' states from a SQLite
activity log, then fans state out over `/ws/status`. See `01-office-overview.png`
and `09-building-closeup.png`.

What genuinely works and should be kept:

- The core illusion is good. Characters walking to role-specific rooms and
  sitting down to work is a more honest and more memorable metaphor than a
  dashboard of dots. The pixel art coheres (warm wood rooms, consistent
  furniture, plants, posters, clocks, staircases).
- It is a real distributed system, not a mock. State maps to zones, the
  WebSocket fan-out is real, and there are 50 backend tests plus CI.
- There is real data behind it. The activity log holds 809 events; the jobs
  pipeline has a real funnel (35 discovered, 34 rejected by filter, 90 rejected
  by the LLM, 2 scored); the `llm_calls` table records per-call model, tokens,
  cost, latency, and ok/error.
- The parchment popups (`03`, `04`) are characterful and readable, and the
  larger tabbed modals (`05`, `07`, `08`) expose real history, discoveries, and
  scores. The offline-dimming and reconnect logic are honest and defensive.

The honest gap: a person who opens this cold does not understand what they are
looking at. The art says "cute game," not "live observability of real AI
agents," and the strongest part of the story (a real, measurable system) is
hidden behind clicking tiny monitors. The biggest wins below are about
legibility and first impression, not about redrawing art that already looks good.

---

## 2. Top priorities (master ranked list)

If you only greenlight a handful, do these, in this order. IDs link to the
detailed entries in Section 3.

1. **D1 Live activity ticker** (small effort, huge legibility win)
2. **A3 Always-on live-status HUD** for the four agents
3. **F1 Fix the cost ticker honesty + the 4,552 failed LLM calls** (currently looks broken)
4. **A2 Room labels and a zone legend**
5. **A1 Cold-open onboarding overlay** ("what am I looking at")
6. **A4 Honest offline / connecting banner**
7. **D2 + D3 A real metrics dashboard view and a jobs funnel** (the "measurable system" angle)
8. **E2 Self-contained demo / replay** so the cold-open is alive without external services
9. **C1 + C2 Unify the popups and give Control a real panel**
10. **B2 State LEDs / status glow above each agent**

Rationale for the ordering: items 1 to 6 are mostly cheap, additive (low risk to
existing features), and directly fix the "I do not understand this" problem that
costs you the recruiter in the first five seconds. Items 7 to 10 are higher
effort but are what turn it from "charming" into "this person ships real,
observable systems."

---

## 3. Proposals, grouped

Each item lists: What, Why it matters for a recruiter, Effort (small / medium /
large), Risk to existing features (low / med / high), and whether it is a Taste
call you should weigh in on or an obvious win.

### Group A: First impression and information design (highest leverage)

**A1. Cold-open onboarding overlay**
- What: A dismissible intro card on first load: one sentence on what this is
  ("a live control room for real AI agents I run"), a "these characters are
  driven by real backend state" line, and a "click anything" nudge. Remember
  dismissal in localStorage. Optionally a 3-step guided tour.
- Why: A recruiter opens cold with no context. Five seconds decides whether they
  read on. Right now nothing tells them this is real or how to engage.
- Effort: medium. Risk: low (additive overlay). Taste call: yes (tone and how
  much text; too much kills the playful feel).

**A2. Room labels and a zone legend**
- What: Label each room on or beside the building (Control, Thinking, Library,
  Comms, Browse, Writing, Lounge) and add a small legend mapping zone to meaning
  ("Browse = fetching the web", "Thinking = LLM analysis", etc.).
- Why: A viewer cannot currently decode the zones (see `09`); the whole
  state-to-place metaphor is invisible without this. This is the cheapest way to
  make the core idea legible.
- Effort: small to medium. Risk: low to medium (drawing text over the locked
  canvas needs care with coordinates). Taste call: yes (labels baked into the
  pixel art vs a clean HTML overlay / side legend).

**A3. Always-on live-status HUD**
- What: A persistent strip or sidebar listing the four agents with a colored
  status dot, the current human-readable state, the current action text if any,
  and "last updated Ns ago." Today this information only appears when you click
  an agent.
- Why: This is the core promise ("situational awareness at a glance"). Making it
  always visible is what separates an observability tool from a toy. It also
  immediately signals "this is live."
- Effort: medium. Risk: low (HTML overlay reading existing WS state). Taste call:
  small (placement and density).

**A4. Honest offline / connecting banner**
- What: When Deal Hunter (or any agent) is offline or the WS is reconnecting,
  show a clear, non-alarming note ("Deal Hunter: offline, its scanner service is
  not running"). Distinguish "offline" from "broken."
- Why: Today an offline agent is just a faded sprite with a dim label (see Deal
  Hunter at the bottom of `09`). To a cold viewer that reads as broken, not as
  honest degradation. Turning it into a clear, deliberate state is a credibility
  win and reinforces the "nothing fake" value.
- Effort: small. Risk: low. Taste call: no (obvious win).

### Group B: Visual polish and cohesion

**B1. Make the building larger / more screen-filling and responsive**
- What: Scale the office up so it commands the viewport (it currently sits small
  and centered, see `01`), and make it gracefully resize.
- Why: First impression and "wow." A bigger stage reads as more substantial.
- Effort: medium. Risk: medium (the canvas uses many hardcoded pixel
  coordinates; scaling the wrapper is safer than rescaling internals). Taste
  call: yes (how big, and whether to crop the background).

**B2. State LEDs / status glow above each agent**
- What: A small colored indicator above each character encoding its current
  state (for example blue scanning, green researching, magenta writing). The
  README already describes this feature, but the current "living office" build
  does not implement it (it uses small work-bubbles when seated instead).
- Why: Instant, glanceable state read tied to the character, and it closes a
  gap between the README and the actual build.
- Effort: small to medium. Risk: low to medium. Taste call: small.

**B3. Ambient life and depth**
- What: Lit windows, a subtle day/night tint tied to real clock time, gentle
  parallax on the background, a touch more environmental motion.
- Why: Pure feel / "wow." Makes it look alive even when agents are idle.
- Effort: medium to large. Risk: low. Taste call: yes (easy to overdo; risks
  distracting from the data story).

**B4. Building frame and sign polish**
- What: The "AGENT CENTRAL" roof sign is tiny and the building edges are plain.
  Give the building a stronger architectural frame, a marquee sign, maybe a
  ground-floor lobby / reception.
- Why: Branding and a more finished, intentional look.
- Effort: medium. Risk: low to medium. Taste call: yes.

### Group C: Popup and panel system (the brief invites a redesign)

**C1. Unify the popup visual language**
- What: There are currently two different popup systems: small warm parchment
  cards (`03`, `04`) and large navy-headed cream modals (`05`, `07`, `08`).
  Pick one language and apply it consistently, or deliberately keep parchment
  for "flavor / lore" and the modal for "data," but make that split intentional
  and visually obviously two tiers.
- Why: Cohesion. Right now it reads as two eras of UI bolted together.
- Effort: medium. Risk: medium (touches shared CSS and several call sites).
  Taste call: yes (this is a core identity decision; the brief explicitly opens
  it up).

**C2. Give Control a real panel instead of "click the tiny monitors"**
- What: The live-stats popup is triggered by clicking a small monitor region and
  shows plain text (`02`). Replace with either a docked Control panel that is
  always present, or a full dashboard view (see D2). Either way, do not hide the
  best content behind a hard-to-find hotspot.
- Why: The control-room stats are the "real measurable system" proof and should
  not be a hidden easter egg.
- Effort: medium to large. Risk: medium. Taste call: yes.

### Group D: Stats and observability (the real differentiator)

**D1. Live activity ticker / feed**
- What: A bottom crawl or a small scrolling feed that narrates real events from
  the activity log as they happen ("Job Analyst scored 'Junior Illustrator' 5/100,
  rejected", "Deal Hunter went offline", "Secretary answered a question"). Drawn
  from `/api/secretary/history` and the live WS.
- Why: This single feature makes "this is a real, live system" undeniable, adds
  constant motion, and is cheap. It is the highest value-to-effort item in the
  whole list.
- Effort: medium. Risk: low (read-only consumer of existing data). Taste call: no
  (obvious win); only the wording/tone is a taste call.

**D2. A real metrics dashboard view (toggle)**
- What: A toggle (for example press Tab, or a "Control Room" button) that flips
  from the office to a genuine metrics dashboard: state-over-time per agent, LLM
  tokens and latency, success vs error rate, calls per hour. The data already
  exists in `llm_calls` and `activity_log`.
- Why: Shows you can build the serious view too, not just the playful one. This
  is what an AI-infra hiring manager actually wants to see, and it pairs the fun
  with rigor.
- Effort: large. Risk: low (a new, separate view). Taste call: yes (how much, and
  whether it lives inline vs a separate route).

**D3. Jobs funnel visualization**
- What: A simple funnel: discovered, rejected by filter, rejected by the LLM,
  scored, notified. Real current numbers are 35 / 34 / 90 / 2 / (few). Show it as
  a funnel or staged bar with the live counts.
- Why: Concrete, legible proof that the agents do real work with real outcomes.
  Recruiters love a funnel because it instantly communicates a working pipeline.
- Effort: medium. Risk: low (read-only). Taste call: no.

**D4. Per-agent detail upgrade**
- What: In each agent popup, add a small sparkline of recent states, the last
  error if any, throughput (jobs/hour, calls/hour), and uptime.
- Why: Turns the popups from text blobs into mini observability panels.
- Effort: medium. Risk: low. Taste call: small.

### Group E: Wow features (feasible and locally self-verifiable)

**E1. "Replay the day" timeline scrubber**
- What: A timeline at the bottom that lets you scrub through the recorded
  activity log and watch the agents re-enact their day (states drive the office
  from history instead of live). You already have 809 timestamped events.
- Why: Memorable and unique. It proves the office is a faithful render of real
  recorded telemetry, not decoration. Great for a demo GIF.
- Effort: large. Risk: medium (needs a clean separation between "live" and
  "replay" state sources). Taste call: yes.

**E2. Self-contained demo / replay mode for cold opens**
- What: A mode that makes the office alive and narrated without requiring the
  external Deal Hunter service, either by replaying recorded real activity or by
  a clearly-labeled synthetic feed. Note: the README advertises `?demo=true`
  with keyboard control, but the current build does not implement any demo flag
  (see F2), so a recruiter following the live link gets a scene that may sit
  mostly static.
- Why: The most common cold open (recruiter, no backend running) currently shows
  a dim, offline-looking Deal Hunter and little motion. A demo/replay mode makes
  the first impression lively while staying honest (clearly labeled as a replay
  or demo).
- Effort: medium. Risk: low to medium. Taste call: yes (it must never look like
  you are faking live data; labeling matters).

**E3. Shareable snapshot / hero refresh**
- What: A clean way to capture a good-looking moment, and a refreshed README
  hero GIF after the polish lands.
- Why: The thing recruiters actually see is often the README, not the live app.
- Effort: small. Risk: low. Taste call: no.

### Group F: Robustness and honesty (unglamorous, important)

**F1. Fix the cost ticker and surface the failed LLM calls honestly**
- What: The top-right ticker reads "LLM today: $0.0000 (3460 calls)" (see `01`,
  `09`). In reality, of 4,644 logged calls, 4,552 failed with HTTP 400, and all
  3,460 of today's calls are failures. So the ticker is counting failed calls as
  "calls" and reporting a real but misleading $0. Two parts: (a) the UI should
  distinguish successful spend / tokens from failed calls and show an error count;
  (b) the Job Analyst is hammering the API with a request that 400s every cycle
  (20 score_errors per pass, every 5 minutes), which is the root cause and should
  be investigated and fixed or backed off.
- Why: A recruiter who notices "$0.0000 (3460 calls)" or who reads the history
  sees something that looks broken. Surfacing it honestly (or fixing the broken
  call) turns a liability into a credibility signal about observability.
- Effort: small to medium for the UI; medium for the root-cause fix/backoff.
  Risk: low (UI), medium (backend behavior change). Taste call: no (this is an
  obvious correctness/honesty fix). NOTE: per the read-only rule I did not fix it;
  flagging it here as instructed.

**F2. Reconcile README and reality (demo mode, LEDs, live link)**
- What: The README describes a `?demo=true` keyboard mode and colored
  state-LEDs above the character. The current "living office" `index.html`
  implements neither (no demo flag handling; work-bubbles instead of LEDs). The
  live-demo link is a cloudflared quick-tunnel that is likely already dead. Either
  restore those features (see B2, E2) or update the README so it matches the
  shipped build.
- Why: A hiring manager who clones the repo and tries the documented demo flow,
  or clicks a dead live link, loses trust. Honesty is one of your stated values.
- Effort: small (doc) to medium (restore features). Risk: low. Taste call: no.

**F3. Better empty and error states in panels**
- What: The Ask Secretary tab is just blank until you type (`06`); some panels
  could read as broken when empty or when the API key is missing. Add friendly
  empty states and clear "needs ANTHROPIC_API_KEY" messaging.
- Why: Polish and graceful degradation; a recruiter without your API key should
  still understand what each panel would do.
- Effort: small. Risk: low. Taste call: no.

**F4. Job Analyst backoff when misconfigured**
- What: If the LLM call keeps 400-ing, stop retrying every 5 minutes; back off,
  log once, and surface "analyst paused: misconfigured" rather than logging
  thousands of failed $0 calls into the DB.
- Why: Prevents the data pollution that causes F1, and is just good agent
  hygiene (the kind of thing the role is hiring for).
- Effort: medium. Risk: medium (changes agent loop behavior). Taste call: no.

### Group G: Portfolio and code hygiene (optional)

**G1. Modularize the frontend**
- What: `index.html` is a single 45KB file mixing CSS, the canvas engine, state
  machine, pathfinding, popups, and interactivity. Consider splitting into a few
  files and adding a short "frontend architecture" note.
- Why: If a reviewer opens the source (they sometimes do), a tidy structure
  signals engineering maturity. It also lowers the risk of the larger items above.
- Effort: medium. Risk: medium (refactor of working code; do it behind tests or
  very carefully). Taste call: yes (worth it only if you expect source review).

**G2. A few frontend smoke checks**
- What: Even one Playwright check that the page loads, the canvas mounts, and a
  popup opens would protect the visual layer during the build run. The README
  currently and reasonably scopes frontend tests out.
- Why: De-risks all the visual changes proposed here.
- Effort: medium. Risk: low. Taste call: yes.

---

## 4. Trade-offs and things I am not sure about

- **Playful vs serious.** The whole identity rests on "serious system, playful
  skin." Several proposals (D2 dashboard, A3 HUD, D1 ticker) push toward
  legibility and rigor. There is a real risk of over-instrumenting the screen
  until the charming office becomes a noisy dashboard. My instinct: keep the
  office as the hero, add one always-on status strip and one ticker, and put the
  heavy charts behind a deliberate toggle (D2) rather than on the main view.
- **Room labels on-art vs overlay (A2).** Baking labels into the pixel art is
  more cohesive but risks cluttering nice art and is fiddly with the locked
  coordinates. A clean HTML overlay is safer and easier but can feel like two
  layers. This is genuinely your call.
- **Replay mode (E1/E2) honesty.** A replay or demo feed is a great cold-open
  fix, but it must be unmistakably labeled so it never reads as faked live data.
  If that labeling feels clunky, it may not be worth it.
- **Bigger building (B1).** Tempting, but the canvas is full of hardcoded
  coordinates and a "locked building" layout. Rescaling the wrapper is low risk;
  re-laying-out internals is not. I would scope this conservatively.
- **I did not fix the failed LLM calls (F1/F4).** This run is read-only. I want
  to flag clearly that this is the one thing that currently looks broken to an
  outside viewer, so it deserves priority in the build run even though it is not
  glamorous.
- **The jobs agents vs the "AI observability" pitch.** Job Scout / Job Analyst
  are job-hunting agents; the framing is "watch your AI agents work." That is
  fine and real, but if the target role is AI infra, leaning the stats story (D2,
  D3) toward generic agent telemetry (tokens, latency, error rates, state
  durations) rather than job-board specifics may read as more broadly relevant.
  Worth a quick gut-check from you.

---

## 5. Suggested greenlight bundles

So you can approve in chunks:

- **Bundle 1, "Make it legible" (cheap, low risk, do first):** A1, A2, A3, A4,
  D1, F2, F3. This is the highest return and barely touches existing logic.
- **Bundle 2, "Prove it is real":** D2, D3, D4, F1, F4. The observability and
  honesty story.
- **Bundle 3, "Make it feel premium":** B1, B2, B3, B4, C1, C2.
- **Bundle 4, "Wow / memorable":** E1, E2, E3.
- **Bundle 5, "Under the hood" (optional):** G1, G2.

My recommendation: greenlight Bundle 1 in full, plus F1 from Bundle 2 (the cost
ticker), then reassess with fresh screenshots before committing to the heavier
visual and dashboard work.
