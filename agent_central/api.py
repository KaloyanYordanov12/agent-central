import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional, Set

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

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

# --- Job Scout config (new agent, commit 1) ---
JOB_SCOUT_INTERVAL_SECONDS = 10800  # 3 hours

# --- Job Analyst config (new agent, commit 2a) ---
JOB_ANALYST_INTERVAL_SECONDS = 300  # 5 minutes — usually fast no-ops
JOB_ANALYST_SCORE_THRESHOLD = 75
PROFILE_PATH = os.path.join(_PROJECT_ROOT, "data", "profile.yaml")


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


class JobScoutTask:
    """Background task that polls public job sources every few hours, filters,
    and stores survivors in discovered_jobs. Mirrors IndexerTask: the sync HTTP
    + sqlite work runs in a worker thread via asyncio.to_thread.
    """

    def __init__(self, activity_db_path: str,
                 interval_seconds: int = JOB_SCOUT_INTERVAL_SECONDS):
        self.activity_db_path = activity_db_path
        self.interval_seconds = interval_seconds
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        self._task = asyncio.create_task(self._loop())
        logger.info("JobScoutTask started")

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("JobScoutTask stopped")

    async def _loop(self):
        from agent_central import activity_log
        # Announce the agent before the first pass so it appears in the log.
        activity_log.log_event("job_scout", "lifecycle", state="idle",
                               metadata={"event": "first_seen"})
        while True:
            try:
                await asyncio.to_thread(self._run_pass)
            except Exception:
                logger.exception("Job Scout pass failed; will retry next cycle")
            await asyncio.sleep(self.interval_seconds)

    def _run_pass(self):
        # Synchronous body — runs in a thread via asyncio.to_thread.
        from agent_central import job_scout, activity_log

        activity_log.log_event("job_scout", "state_change", state="scanning",
                               metadata={"event": "pass_start"})
        try:
            stats = job_scout.run_scout_pass(self.activity_db_path)
            activity_log.log_event("job_scout", "state_change", state="idle",
                                   payload=stats, metadata={"event": "pass_complete"})
            if stats.get("new", 0):
                logger.info(f"Job Scout pass complete: {stats}")
        except Exception:
            activity_log.log_event("job_scout", "error", state="error",
                                   metadata={"event": "pass_failed"})
            raise


class JobAnalystTask:
    """Background task that scores discovered jobs with Claude Haiku and posts
    Discord notifications for high scorers. Mirrors JobScoutTask. A missing API
    key or profile is handled gracefully (warn + skip the pass) so it can never
    crash the process.
    """

    def __init__(self, activity_db_path: str, profile_path: str,
                 interval_seconds: int = JOB_ANALYST_INTERVAL_SECONDS,
                 threshold: int = JOB_ANALYST_SCORE_THRESHOLD):
        self.activity_db_path = activity_db_path
        self.profile_path = profile_path
        self.interval_seconds = interval_seconds
        self.threshold = threshold
        self._task: Optional[asyncio.Task] = None
        self._client = None  # lazy

    async def start(self):
        self._task = asyncio.create_task(self._loop())
        logger.info("JobAnalystTask started")

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("JobAnalystTask stopped")

    async def _loop(self):
        from agent_central import activity_log
        activity_log.log_event("job_analyst", "lifecycle", state="idle",
                               metadata={"event": "first_seen"})
        while True:
            try:
                await asyncio.to_thread(self._run_pass)
            except Exception:
                logger.exception("Job Analyst pass failed; will retry next cycle")
            await asyncio.sleep(self.interval_seconds)

    def _run_pass(self):
        from agent_central import job_analyst, activity_log

        if not os.path.exists(self.profile_path):
            logger.warning(f"[job_analyst] no profile at {self.profile_path}; skipping pass")
            return
        if self._client is None:
            try:
                self._client = job_analyst.JobAnalystClient()
            except RuntimeError as e:
                logger.warning(f"[job_analyst] {e}; skipping pass")
                return

        webhook = os.environ.get("JOB_SCOUT_DISCORD_WEBHOOK_URL")
        activity_log.log_event("job_analyst", "state_change", state="scanning",
                               metadata={"event": "pass_start"})
        try:
            stats = job_analyst.run_analyst_pass(
                self.activity_db_path, self.profile_path, webhook, self._client,
                threshold=self.threshold,
            )
            activity_log.log_event("job_analyst", "state_change", state="idle",
                                   payload=stats, metadata={"event": "pass_complete"})
            if stats.get("scored", 0) or stats.get("notified", 0):
                logger.info(f"Job Analyst pass complete: {stats}")
        except Exception:
            activity_log.log_event("job_analyst", "error", state="error",
                                   metadata={"event": "pass_failed"})
            raise


_poller: StatusPoller | None = None
_indexer: "IndexerTask | None" = None
_job_scout: "JobScoutTask | None" = None
_job_analyst: "JobAnalystTask | None" = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _poller, _indexer, _job_scout, _job_analyst
    # Ensure the activity-log DB + schema (incl. discovered_jobs) exist first.
    activity_log.init_db(activity_log.DEFAULT_DB_PATH)
    _poller = StatusPoller(broadcast_fn=broadcast)
    await _poller.start()
    _indexer = IndexerTask(
        activity_db_path=activity_log.DEFAULT_DB_PATH,
        vector_dir=CHROMA_DIR,
        state_path=INDEX_STATE_PATH,
    )
    await _indexer.start()
    _job_scout = JobScoutTask(activity_db_path=activity_log.DEFAULT_DB_PATH)
    await _job_scout.start()
    _job_analyst = JobAnalystTask(
        activity_db_path=activity_log.DEFAULT_DB_PATH,
        profile_path=PROFILE_PATH,
    )
    await _job_analyst.start()
    try:
        yield
    finally:
        await _job_analyst.stop()
        await _job_scout.stop()
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


# --- Ask Secretary (Step 3): RAG over the activity vector index ---
_secretary_client = None
_secretary_embedding_service = None
_secretary_vector_index = None


def _get_secretary_deps():
    """Lazily build the Secretary's dependencies.

    Construct the SecretaryClient FIRST so a missing ANTHROPIC_API_KEY fails
    fast (RuntimeError -> 503) before we pay to load the ~80MB embedding model.
    """
    global _secretary_client, _secretary_embedding_service, _secretary_vector_index
    from agent_central import secretary, indexer

    if _secretary_client is None:
        _secretary_client = secretary.SecretaryClient()  # raises if no API key
    if _secretary_embedding_service is None:
        _secretary_embedding_service = indexer.EmbeddingService()
    if _secretary_vector_index is None:
        _secretary_vector_index = indexer.VectorIndex(CHROMA_DIR)
    return _secretary_client, _secretary_embedding_service, _secretary_vector_index


class AskRequest(BaseModel):
    question: str
    top_k: Optional[int] = None


@app.post("/api/secretary/ask")
async def secretary_ask(payload: AskRequest):
    """Answer a natural-language question about agent activity (RAG)."""
    if not payload.question.strip():
        raise HTTPException(status_code=400, detail="question cannot be empty")

    try:
        client, embedding_service, vector_index = _get_secretary_deps()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    top_k = min(payload.top_k or 5, 20)

    from agent_central import secretary
    # Living-office hook: mark the Secretary 'answering' while it works (the only
    # backend change in stage G). The poller broadcasts it via agent_states and
    # the visual walks the Secretary to Comms, then back to idle on completion.
    try:
        activity_log.log_event("secretary", "state_change", state="answering",
                               metadata={"event": "ask_start"})
    except Exception:
        logger.exception("secretary state (answering) failed")
    try:
        result = await asyncio.to_thread(
            secretary.ask_secretary,
            payload.question, vector_index, embedding_service, client,
            top_k=top_k,
        )
    except Exception:
        logger.exception("Secretary ask failed")
        raise HTTPException(status_code=500, detail="Internal error processing question")
    finally:
        try:
            activity_log.log_event("secretary", "state_change", state="idle",
                                   metadata={"event": "ask_done"})
        except Exception:
            logger.exception("secretary state (idle) failed")

    return result


# --- Jobs / cost read-only endpoints (commit 2b) ---
@app.get("/api/jobs/discovered")
def jobs_discovered(source: Optional[str] = None, status: Optional[str] = None,
                    limit: int = 50):
    """Discovered jobs (newest first) + status/source breakdowns."""
    from agent_central import job_scout
    try:
        return job_scout.get_discovered(activity_log._DB_PATH, source=source,
                                        status=status, limit=limit)
    except Exception:
        logger.exception("jobs/discovered failed")
        raise HTTPException(status_code=500, detail="failed to load discovered jobs")


@app.get("/api/jobs/analyst-activity")
def jobs_analyst_activity(limit: int = 20):
    """Recent Job Analyst scoring activity + today's summary."""
    from agent_central import job_analyst
    try:
        return job_analyst.get_recent_activity(activity_log._DB_PATH, limit=limit)
    except Exception:
        logger.exception("jobs/analyst-activity failed")
        raise HTTPException(status_code=500, detail="failed to load analyst activity")


@app.get("/api/llm-costs/today")
def llm_costs_today():
    """Today's (UTC) aggregated LLM spend for the Cost Today indicator."""
    try:
        return activity_log.get_costs_today(activity_log._DB_PATH)
    except Exception:
        logger.exception("llm-costs/today failed")
        raise HTTPException(status_code=500, detail="failed to load llm costs")


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
