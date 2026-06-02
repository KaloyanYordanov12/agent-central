# Agent Central

Multi-agent orchestration command center. Build, slot, and monitor agents from a single visual interface.

Currently in early development. Phase 1: command center + agent interface + slot Deal Hunter as Agent #1.

## Architecture

- FastAPI backend
- Single-file HTML+CSS+JS frontend
- Agent abstract base class — each agent is a Python module implementing the Agent interface
- Agent registry singleton manages all live agents
- Manual trigger pattern (agents run on demand, not continuously)

## Running locally

.\venv\Scripts\python.exe -m uvicorn agent_central.api:app --host 127.0.0.1 --port 8001

Visit http://127.0.0.1:8001

## Running tests

```bash
# Install dev dependencies once
pip install -r requirements-dev.txt

# Run the test suite
pytest tests/ -v
```

The test suite covers backend endpoints (`/health`, `/api/agents`, static
serving), the WebSocket connection lifecycle, the `broadcast()` helper, the
`StatusPoller` initial state, and the agent-state / `STATE_TO_ZONE` contracts.
CI runs them on every push and PR via GitHub Actions (`.github/workflows/test.yml`).

Note: Agent Central learns Deal Hunter's state by polling its HTTP `/status`
endpoint (not file-based IPC), so the tests exercise that polling/broadcast
path rather than any status file.

Frontend tests (Phaser scene, browser automation) are intentionally out of
scope for this iteration — Playwright setup overhead isn't worth it for a
single-developer project at this stage.

## Status

Step 1 complete: project skeleton + agent interface + empty command center UI.
No agents implemented yet.
