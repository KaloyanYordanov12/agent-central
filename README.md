# Agent Central

> A real-time observatory for AI agents at work. Watch your agents like you'd watch your colleagues across the office floor — see what they're doing, when, and where.

https://github.com/user-attachments/assets/d029066d-9fd6-4c90-8a44-6409291fa107

**Run it:** locally on `127.0.0.1:8001` (see "Running it locally"). Public demos have used ephemeral cloudflared quick-tunnels, so there is no permanent hosted link.
**Built:** May to June 2026, ~48 hours from skeleton to shipped

---

## What this is

Agent Central is a visual command center for the AI agents I'm building. Instead of staring at log files or dashboards full of metrics, you see a pixel-art office where each agent is a character that walks between workstations based on what they're actually doing.

When Deal Hunter (a Reddit lead-scout agent) is scanning subreddits, his character walks to the Operations zone. When he's writing a DM, he walks to the Writing Desk. When he's idle between cycles, he hangs out in the Lounge. The whole thing is driven by real backend state — not a simulation.

It's a serious distributed system with a deliberately playful interface.

---

## Why I built it

Running an AI agent for real work means staring at terminal logs for hours. That's fine for debugging but terrible for situational awareness — you can't tell at a glance whether the agent is healthy, what it's working on, or whether multiple agents are stepping on each other.

I wanted to fix that. And honestly, I wanted to make it fun to look at.

The deeper design idea: agents are workers. They have shifts, tasks, downtime. Visualizing them as people in an office is more honest about what they actually are than yet another dashboard with green/red dots.

---

## What it does

- **Watches an AI agent's pipeline state in real time** via WebSocket
- **Maps agent state to physical zones** in a pixel-art office (operations, communications, writing desk, research, lounge)
- **Drives an autonomous character** that walks between zones, takes elevators between floors
- **Surfaces live state everywhere you look:** an always-on status strip (one row per agent with state, current action, and "updated Ns ago"), a scrolling activity ticker narrating real events from the activity log, a jobs pipeline funnel, labelled rooms, and a work bubble above an agent when it is at a desk
- **Offers clickable interactive elements** with quest-screen-style popups: each agent, the control-room screens (live LLM spend/usage), and flavor objects around the office
- **Onboards a cold viewer** with a dismissible intro card, and **degrades honestly**: an offline agent dims and a calm banner explains its separate service is not running (offline, not broken)

---

## Architecture

Two-service distributed system:

```
┌─────────────────┐        ┌──────────────────┐         ┌──────────────────┐
│   Deal Hunter   │        │  Agent Central   │         │   Browser UI     │
│  (port 8000)    │        │  (port 8001)     │         │  (Canvas + CSS)  │
│                 │        │                  │         │                  │
│  Reddit scanner │ HTTP   │  FastAPI server  │ WS push │  Office + walking│
│  + dashboard    ├───────▶│  + status poller ├────────▶│  agents + HUD +  │
│                 │ /status│                  │         │  ticker + popups │
└─────────────────┘  poll  └──────────────────┘         └──────────────────┘
```

**Why HTTP polling instead of direct calls or shared memory:** Deal Hunter is a long-running scanner; Agent Central is a separate process that can restart independently. HTTP polling means the scanner doesn't care whether the observatory is up, and the observatory can attach/detach without affecting agent work. The 1.5s poll is the latency floor — fine for visualizing human-readable pipeline states, intentionally over-engineered would be a problem at higher-frequency telemetry.

**Why WebSocket fan-out:** Multiple browser clients can watch the same agent simultaneously. Cheap to add, plays nicely with browser reconnects.

**Why a hand-rolled canvas for the office:** the building and the walking agents are drawn on a single HTML5 canvas (an offscreen buffer rendered at native pixel size, then blitted scaled with smoothing off for crisp pixel art) on a `requestAnimationFrame` loop, with A* / Dijkstra pathfinding over a walkable node graph. An earlier iteration used Phaser; the raw-canvas rewrite is smaller and gives full control over the pixel grid. The world chrome around the canvas (sky background, status HUD, activity ticker, zone legend, jobs funnel, popups) is plain HTML/CSS, which is more reliable for static overlays.

---

## Tech stack

- **Backend:** FastAPI, uvicorn, websockets, httpx
- **Frontend:** vanilla HTML/CSS/JS with a hand-rolled HTML5 canvas renderer (no framework)
- **Art:** Custom pixel art from [rixitic](https://rixitic.itch.io/) (interior tileset, $1 strategic asset purchase) + [2dPig](https://2dpig.itch.io/) (character sprites) + AI-generated background
- **Testing:** pytest, pytest-asyncio (100+ backend tests covering the API, status polling, WebSocket, activity logging, the background indexer, the RAG endpoint, the jobs/cost endpoints, and the Job Analyst including its backoff; CI-validated)
- **CI:** GitHub Actions, runs tests on every push and PR
- **Deployment:** uvicorn locally; past public demos used ephemeral cloudflared quick-tunnels, so there is no permanent hosted URL

---

## Running it locally

```bash
# 1. Start Deal Hunter (port 8000)
cd dealhunter
.\venv\Scripts\python.exe -m uvicorn dashboard.api:app --host 127.0.0.1 --port 8000

# 2. Start Agent Central (port 8001)
cd agentcentral
.\venv\Scripts\python.exe -m uvicorn agent_central.api:app --host 127.0.0.1 --port 8001

# 3. Open in browser
#   http://127.0.0.1:8001
```

Agent Central runs on its own (port 8001): the office, the status HUD, the
activity ticker, the jobs funnel, and the popups all work from its own data even
when Deal Hunter (port 8000) is not running. In that case Deal Hunter simply shows
as offline (with a calm banner that says so) and the other agents keep updating.

---

## Running tests

```bash
# Install dev dependencies once
pip install -r requirements-dev.txt

# Run the test suite
pytest tests/ -v
```

The test suite covers backend endpoints (`/health`, `/api/agents`, static serving), the WebSocket connection lifecycle, the `broadcast()` helper, the `StatusPoller` initial state, the agent-state / `STATE_TO_ZONE` contracts, the activity log (SQLite IPC + `/api/secretary/history`), the background indexer (chunking, summarization, embeddings, vector store, index-pass idempotency), and the Secretary RAG layer (`/api/secretary/ask`, with the Anthropic client mocked — no real API calls). CI runs them on every push and PR via GitHub Actions.

Frontend tests (canvas scene, browser automation) are intentionally out of scope for this iteration. The visual layer is verified by hand and with scripted Chrome DevTools Protocol screenshots instead.

---

## Secretary

The Secretary is an agent inside Agent Central that lets you ask natural-language questions about what your agents have been doing.

Click the blue character labeled "Secretary" at the lower-left of the office, and a floating popup opens with two tabs:

- **History** — a chronological log of agent activity (state changes, lifecycle events, and errors) captured from the agents Agent Central is observing. Filter by agent, by time, or by event type.
- **Ask Secretary** — type a question like "What has Deal Hunter been doing today?" or "Were there any errors this week?" and the Secretary retrieves the relevant activity, calls Claude Haiku, and returns an answer with source citations.

### How it works

Three pieces stitched together:

1. **Activity logging.** Every state change and lifecycle event observed by the status poller is persisted to a local SQLite database (`data/activity.db`). The log is append-only — no events are overwritten or deleted.

2. **Background indexer.** Every five minutes, a background task reads new events, groups them into 15-minute activity windows per agent, summarizes each window mechanically (no LLM), embeds the summaries with a local sentence-transformers model, and stores them in a persistent ChromaDB vector index at `data/chroma/`. No API costs.

3. **RAG endpoint.** `POST /api/secretary/ask` embeds the question, retrieves the top-K relevant chunks, prompts Claude Haiku with the retrieved context, and returns the answer plus source citations. The call is wrapped in `asyncio.to_thread` so the LLM request never blocks the event loop.

The Ask tab requires `ANTHROPIC_API_KEY` to be set in the environment (a missing key returns a clear 503). The History tab works with no API key at all.

### Demo

The demo video at the top of this README shows the original office before the Secretary was added. Clone the repo, start the server, and the Secretary character appears in the office at the lower-left, ready to click.

---

## Status

**What works:** Everything in this README. The system runs, the agents walk between rooms, the popups open, the always-on status HUD and activity ticker track live state, the jobs funnel shows the real pipeline, and the test suite is green.

**What's pending:** Deal Hunter's Reddit scanner is currently blocked on a 403 from Reddit's CDN; they have tightened their bot detection beyond what a header workaround can solve. Restoring it requires either PRAW pre-approval (Reddit's official policy, a multi-week approval process) or rotating residential proxies. The architecture is platform-agnostic: once data flows in, the visualization pipeline reacts in real time.

**What's next:** Multi-agent support (the Agent base class + registry is already there; just need to add the second agent), expanding zone interactions, and a more sophisticated background.

---

## Why this looks the way it does

Some design decisions worth flagging because they shaped the whole thing:

**Parchment quest-screen popups instead of terminal-style overlays:** Early popups were black backgrounds with amber JetBrains Mono text — classic developer terminal look. They clashed badly against the painted world. Switched to a warm parchment palette (cream background, dark brown text, double-line border, circular wax-seal close button) and everything cohered. The popups now feel like NPC dialogue from an RPG instead of console output.

**Navy mounted status plaque, not a corner HUD:** The AGENT CENTRAL sign on the building's roof established a visual language (navy plate, off-white text, JetBrains Mono). The status overlay inside the building uses the same palette so it reads as a mounted info plaque on the building's interior wall, not as floating UI.

**Always-on legibility over hidden depth:** the strongest part of the story is that this is a real, measurable system, so that state is surfaced up front rather than hidden behind clicks. A status strip, a live activity ticker narrating real events, labelled rooms with a zone legend, and a jobs pipeline funnel mean a first-time viewer understands what they are looking at in a few seconds, and that it is driven by real agents.

**Honest degradation, nothing faked:** when a backend agent's service is not running, that agent dims and a calm banner explains it is offline (not broken), and the cost ticker separates successful LLM spend from failed calls rather than reporting failures as free calls. The goal is that nothing on screen overstates what the system is actually doing.

---

## Acknowledgements

- **[rixitic](https://rixitic.itch.io/)** — gorgeous pixel office tileset
- **[2dPig](https://2dpig.itch.io/)** — clean character sprites
- **Claude (Anthropic)** — paired on architecture decisions and implementation throughout. The honest moments where we hit dead ends and had to revert (CSS building exterior, floor pulse animations) were as valuable as the wins
