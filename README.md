# Agent Central

> A real-time observatory for AI agents at work. Watch your agents like you'd watch your colleagues across the office floor — see what they're doing, when, and where.

https://github.com/user-attachments/assets/d029066d-9fd6-4c90-8a44-6409291fa107

**Live demo:** https://remove-procedures-deliver-letters.trycloudflare.com/?demo=true
**Built:** May–June 2026, ~48 hours from skeleton to shipped

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
- **Surfaces state through colored LEDs** above the character (blue = scanning, green = researching, magenta = writing, cyan = posting)
- **Offers 8 clickable interactive elements** with quest-screen-style popups: agent profile, workstation info, metrics whiteboard, water cooler easter egg, system info panel, team overview, outside-world API health, printer activity log
- **Supports demo mode** (`?demo=true`) for keyboard-driven walkthroughs when the backend isn't actively producing state events

---

## Architecture

Two-service distributed system:

```
┌─────────────────┐        ┌──────────────────┐         ┌──────────────────┐
│   Deal Hunter   │        │  Agent Central   │         │   Browser UI     │
│  (port 8000)    │        │  (port 8001)     │         │  (Phaser + CSS)  │
│                 │        │                  │         │                  │
│  Reddit scanner │ HTTP   │  FastAPI server  │ WS push │  Character +     │
│  + dashboard    ├───────▶│  + status poller ├────────▶│  zone LEDs +     │
│                 │ /status│                  │         │  popups          │
└─────────────────┘  poll  └──────────────────┘         └──────────────────┘
```

**Why HTTP polling instead of direct calls or shared memory:** Deal Hunter is a long-running scanner; Agent Central is a separate process that can restart independently. HTTP polling means the scanner doesn't care whether the observatory is up, and the observatory can attach/detach without affecting agent work. The 1.5s poll is the latency floor — fine for visualizing human-readable pipeline states, intentionally over-engineered would be a problem at higher-frequency telemetry.

**Why WebSocket fan-out:** Multiple browser clients can watch the same agent simultaneously. Cheap to add, plays nicely with browser reconnects.

**Why Phaser for the office:** I needed pixel-art rendering, animated character movement, and zone-based tweening. Phaser handles all three. The world chrome around it (sky background, building, popups, LEDs) is HTML/CSS — pure browser primitives are more reliable than fighting Phaser's quirks for static layout.

---

## Tech stack

- **Backend:** FastAPI, uvicorn, websockets, httpx
- **Frontend:** Phaser 3.90, vanilla HTML/CSS/JS
- **Art:** Custom pixel art from [rixitic](https://rixitic.itch.io/) (interior tileset, $1 strategic asset purchase) + [2dPig](https://2dpig.itch.io/) (character sprites) + AI-generated background
- **Testing:** pytest, pytest-asyncio (50 backend tests covering the API, status polling, WebSocket, activity logging, the background indexer, and the RAG endpoint; CI-validated)
- **CI:** GitHub Actions, runs tests on every push and PR
- **Deployment:** uvicorn locally, cloudflared quick-tunnels for remote demos

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
# Production view:           http://127.0.0.1:8001
# Demo mode (keyboard test): http://127.0.0.1:8001/?demo=true
```

In demo mode, keys 1-5 walk the character between zones manually. The D key toggles demo mode on/off mid-session.

---

## Running tests

```bash
# Install dev dependencies once
pip install -r requirements-dev.txt

# Run the test suite
pytest tests/ -v
```

The test suite covers backend endpoints (`/health`, `/api/agents`, static serving), the WebSocket connection lifecycle, the `broadcast()` helper, the `StatusPoller` initial state, the agent-state / `STATE_TO_ZONE` contracts, the activity log (SQLite IPC + `/api/secretary/history`), the background indexer (chunking, summarization, embeddings, vector store, index-pass idempotency), and the Secretary RAG layer (`/api/secretary/ask`, with the Anthropic client mocked — no real API calls). CI runs them on every push and PR via GitHub Actions.

Frontend tests (Phaser scene, browser automation) are intentionally out of scope for this iteration — Playwright setup overhead isn't worth it for a single-developer project at this stage.

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

**What works:** Everything in this README. The system runs, the character walks, the popups open, the LEDs track state, the tunnel exposes it externally for sharing, and the test suite is green.

**What's pending:** Deal Hunter's Reddit scanner is currently blocked on a 403 from Reddit's CDN — they've tightened their bot detection beyond what a header workaround can solve. Restoring it requires either PRAW pre-approval (Reddit's official policy, multi-week approval process) or rotating residential proxies. The architecture is platform-agnostic — once data flows in, the visualization pipeline reacts in real time.

**What's next:** Multi-agent support (the Agent base class + registry is already there; just need to add the second agent), expanding zone interactions, and a more sophisticated background.

---

## Why this looks the way it does

Some design decisions worth flagging because they shaped the whole thing:

**Parchment quest-screen popups instead of terminal-style overlays:** Early popups were black backgrounds with amber JetBrains Mono text — classic developer terminal look. They clashed badly against the painted world. Switched to a warm parchment palette (cream background, dark brown text, double-line border, circular wax-seal close button) and everything cohered. The popups now feel like NPC dialogue from an RPG instead of console output.

**Navy mounted status plaque, not a corner HUD:** The AGENT CENTRAL sign on the building's roof established a visual language (navy plate, off-white text, JetBrains Mono). The status overlay inside the building uses the same palette so it reads as a mounted info plaque on the building's interior wall, not as floating UI.

**Demo mode flag:** Building a state visualization for events that don't fire is frustrating. The `?demo=true` flag bypasses the WebSocket and lets keyboard inputs drive the system directly. Same character, same LEDs, same popups, just with manual triggers. Real WebSocket events take over the moment demo mode is off.

---

## Acknowledgements

- **[rixitic](https://rixitic.itch.io/)** — gorgeous pixel office tileset
- **[2dPig](https://2dpig.itch.io/)** — clean character sprites
- **Claude (Anthropic)** — paired on architecture decisions and implementation throughout. The honest moments where we hit dead ends and had to revert (CSS building exterior, floor pulse animations) were as valuable as the wins
