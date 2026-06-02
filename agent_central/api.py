import asyncio
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


# --- Secretary background indexer config (Step 2) ---
_PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
CHROMA_DIR = os.path.join(_PROJECT_ROOT, "data", "chroma")
INDEX_STATE_PATH = os.path.join(_PROJECT_ROOT, "data", "index_state.json")
INDEX_INTERVAL_SECONDS = 300
CHUNK_WINDOW_MINUTES = 15


class IndexerTask:
    """Background task that periodically indexes activity_log events into the
    vector store. Mirrors StatusPoller's lifecycle; kept separate from it.

    The indexing pass (sync ChromaDB + sentence-transformers work) runs in a
    worker thread via asyncio.to_thread so it never blocks the event loop. The
    embedding model + heavy modules load lazily on the first pass.
    """

    def __init__(self, activity_db_path: str, vector_dir: str, state_path: str,
                 interval_seconds: int = INDEX_INTERVAL_SECONDS,
                 window_minutes: int = CHUNK_WINDOW_MINUTES):
        self.activity_db_path = activity_db_path
        self.vector_dir = vector_dir
        self.state_path = state_path
        self.interval_seconds = interval_seconds
        self.window_minutes = window_minutes
        self._task: Optional[asyncio.Task] = None
        self._embedding_service = None  # lazy

    async def start(self):
        self._task = asyncio.create_task(self._loop())
        logger.info("IndexerTask started")

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("IndexerTask stopped")

    async def _loop(self):
        while True:
            try:
                await asyncio.to_thread(self._run_pass)
            except Exception:
                logger.exception("Indexer pass failed; will retry next cycle")
            await asyncio.sleep(self.interval_seconds)

    def _run_pass(self):
        # Synchronous body — runs in a thread via asyncio.to_thread.
        from agent_central import indexer

        if self._embedding_service is None:
            self._embedding_service = indexer.EmbeddingService()
        state = indexer.IndexState.load(self.state_path)
        stats = indexer.run_index_pass(
            self.activity_db_path, self.vector_dir, self._embedding_service, state,
            window_minutes=self.window_minutes,
        )
        if stats["new_chunks"]:
            logger.info(f"Indexer pass complete: {stats}")


_poller: StatusPoller | None = None
_indexer: "IndexerTask | None" = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _poller, _indexer
    # Ensure the activity-log DB + schema exist before the poller starts logging.
    activity_log.init_db(activity_log.DEFAULT_DB_PATH)
    _poller = StatusPoller(broadcast_fn=broadcast)
    await _poller.start()
    _indexer = IndexerTask(
        activity_db_path=activity_log.DEFAULT_DB_PATH,
        vector_dir=CHROMA_DIR,
        state_path=INDEX_STATE_PATH,
    )
    await _indexer.start()
    try:
        yield
    finally:
        await _indexer.stop()
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
