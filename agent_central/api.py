import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from agent_central import activity_log
from agent_central.poller import StatusPoller
from agent_central.registry import registry

logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# Connected WebSocket clients
_ws_clients: Set[WebSocket] = set()


async def broadcast(message: dict) -> None:
    """Send a message to all connected WS clients. Drops disconnected ones."""
    if not _ws_clients:
        return
    text = json.dumps(message)
    dead: Set[WebSocket] = set()
    for ws in _ws_clients:
        try:
            await ws.send_text(text)
        except Exception:
            dead.add(ws)
    _ws_clients.difference_update(dead)


_poller: StatusPoller | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _poller
    # Ensure the activity-log DB + schema exist before the poller starts logging.
    activity_log.init_db(activity_log.DEFAULT_DB_PATH)
    _poller = StatusPoller(broadcast_fn=broadcast)
    await _poller.start()
    try:
        yield
    finally:
        await _poller.stop()


app = FastAPI(title="Agent Central", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "agent_count": registry.count()}


@app.get("/api/agents")
def list_agents():
    """Return list of all registered agents with their status."""
    result = []
    for agent_id, agent in registry.all().items():
        try:
            status = agent.status()
        except Exception as e:
            status = {"state": "error", "message": str(e), "last_run": None}
        result.append({
            "id": agent.id,
            "name": agent.name,
            "description": agent.description,
            "version": agent.version,
            "status": status,
        })
    return {"agents": result, "count": len(result)}


@app.get("/api/agents/{agent_id}/status")
def agent_status(agent_id: str):
    agent = registry.get(agent_id)
    if not agent:
        return {"error": "agent not found", "agent_id": agent_id}, 404
    return agent.status()


@app.get("/api/agents/{agent_id}/recent")
def agent_recent(agent_id: str, limit: int = 10):
    agent = registry.get(agent_id)
    if not agent:
        return {"error": "agent not found", "agent_id": agent_id}, 404
    return {"items": agent.recent_activity(limit=limit)}


@app.post("/api/agents/{agent_id}/trigger")
def agent_trigger(agent_id: str):
    agent = registry.get(agent_id)
    if not agent:
        return {"error": "agent not found", "agent_id": agent_id}, 404
    return agent.trigger()


@app.get("/api/secretary/history")
def secretary_history(
    agent_id: Optional[str] = None,
    event_type: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """Query persisted agent activity. Foundation for the Secretary agent.

    `total` is the count for the agent_id filter (per get_event_count's contract);
    `events` is the matching page, newest first. limit is capped at 1000.
    """
    events = activity_log.query_events(
        agent_id=agent_id,
        event_type=event_type,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    total = activity_log.get_event_count(agent_id)
    return {"total": total, "events": events}


# Serve the command center UI
@app.get("/")
def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.websocket("/ws/status")
async def status_ws(websocket: WebSocket):
    """Streams Deal Hunter state updates from the poller to the browser."""
    await websocket.accept()
    _ws_clients.add(websocket)
    logger.info(f"WS client connected. Total: {len(_ws_clients)}")
    try:
        while True:
            # Block on client messages to keep connection open; we don't expect any.
            await websocket.receive_text()
    except WebSocketDisconnect:
        _ws_clients.discard(websocket)
        logger.info(f"WS client disconnected. Total: {len(_ws_clients)}")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
