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

## Status

Step 1 complete: project skeleton + agent interface + empty command center UI.
No agents implemented yet.
