# Agent Central

> A real-time observatory for AI agents at work. Watch your agents like you'd watch your colleagues across the office floor — see what they're doing, when, and where.

https://github.com/user-attachments/assets/f22bb881-5ced-4ff6-b30d-c2dbc3573df2

**Live demo:** [demo link goes here]
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
- **Testing:** pytest, pytest-asyncio (15 backend tests, CI-validated)
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

The test suite covers backend endpoints (`/health`, `/api/agents`, static serving), the WebSocket connection lifecycle, the `broadcast()` helper, the `StatusPoller` initial state, and the agent-state / `STATE_TO_ZONE` contracts. CI runs them on every push and PR via GitHub Actions.

Frontend tests (Phaser scene, browser automation) are intentionally out of scope for this iteration — Playwright setup overhead isn't worth it for a single-developer project at this stage.

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
