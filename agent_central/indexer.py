"""
Background activity indexer for the Secretary agent (Step 2).

Reads activity_log events, groups them into fixed time windows per agent,
mechanically summarizes each window (no LLM), embeds the summaries with a local
sentence-transformers model, and upserts them into a persistent ChromaDB
collection. Append-only: progress is tracked by the last indexed event id.

Heavy imports (sentence_transformers, chromadb) are deferred to first use so
that importing this module — and api.py, which references it — stays cheap.
"""
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from agent_central import activity_log

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


# ----------------------------------------------------------------------------
# Embeddings
# ----------------------------------------------------------------------------
class EmbeddingService:
    """Lazy-loading wrapper around a sentence-transformers model.

    The model (~80MB) loads on the first embed_texts() call and is cached for
    the process lifetime — loading is slow (~3-5s), so do it once.
    """

    def __init__(self, model_name: str = EMBEDDING_MODEL):
        self.model_name = model_name
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model {self.model_name} (first use)...")
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._ensure_model()
        vectors = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        return [[float(x) for x in v] for v in vectors]


# ----------------------------------------------------------------------------
# Chunking + summarization (pure, no model / no DB)
# ----------------------------------------------------------------------------
@dataclass
class Chunk:
    chunk_id: str
    agent_id: str
    window_start: str  # ISO 8601
    window_end: str    # ISO 8601
    event_count: int
    summary: str
    event_ids: list[int]
    states_seen: list[str]


def _parse_ts(ts_str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None


def _floor_to_window(ts: datetime, window_minutes: int) -> datetime:
    """Floor a datetime to the start of its window_minutes bucket (clock-aligned)."""
    bucket = (ts.minute // window_minutes) * window_minutes
    return ts.replace(minute=bucket, second=0, microsecond=0)


def summarize_chunk(events: list[dict]) -> str:
    """Mechanical (non-LLM) natural-language summary of one chunk's events.

    Pure function — safe with None payloads/metadata. Example:
      "deal_hunter activity 2026-06-02T14:30 to 14:45: 4 events. States: idle ->
       researching -> idle. Lifecycle: 1 (offline). Errors: 0. Actions: '...'."
    """
    if not events:
        return "No activity."

    evs = sorted(events, key=lambda e: e.get("id") or 0)
    agent_id = evs[0].get("agent_id", "unknown")

    first_ts = _parse_ts(evs[0].get("timestamp"))
    last_ts = _parse_ts(evs[-1].get("timestamp"))
    if first_ts and last_ts:
        time_range = f"{first_ts.strftime('%Y-%m-%dT%H:%M')} to {last_ts.strftime('%H:%M')}"
    else:
        time_range = "unknown window"

    # State transition trail: previous_state of the first change, then each new state.
    state_changes = [e for e in evs if e.get("event_type") == "state_change"]
    states_trail = []
    if state_changes:
        first_meta = state_changes[0].get("metadata") or {}
        prev = first_meta.get("previous_state")
        if prev:
            states_trail.append(prev)
        states_trail.extend(e.get("state") for e in state_changes if e.get("state"))

    lifecycle = [e for e in evs if e.get("event_type") == "lifecycle"]
    lifecycle_labels = [
        (e.get("state") or (e.get("metadata") or {}).get("event") or "event")
        for e in lifecycle
    ]
    error_count = sum(1 for e in evs if e.get("event_type") == "error")

    actions = []
    for e in evs:
        payload = e.get("payload")
        if isinstance(payload, dict):
            action = payload.get("current_action")
            if action and action not in actions:
                actions.append(action)

    parts = [
        f"{agent_id} activity {time_range}: "
        f"{len(evs)} event{'s' if len(evs) != 1 else ''}."
    ]
    if states_trail:
        parts.append("States: " + " -> ".join(states_trail) + ".")
    lifecycle_str = f"Lifecycle: {len(lifecycle)}"
    if lifecycle_labels:
        lifecycle_str += " (" + ", ".join(lifecycle_labels) + ")"
    parts.append(lifecycle_str + ".")
    parts.append(f"Errors: {error_count}.")
    if actions:
        parts.append("Actions: " + ", ".join(f"'{a}'" for a in actions) + ".")
    return " ".join(parts)


def chunk_events(events: list[dict], window_minutes: int = 15) -> list[Chunk]:
    """Group events by (agent_id, time window) and summarize each group.

    Returns chunks sorted by (window_start, agent_id). Events with unparseable
    timestamps are skipped.
    """
    groups: dict = {}
    for ev in events:
        ts = _parse_ts(ev.get("timestamp"))
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        window_start = _floor_to_window(ts, window_minutes).isoformat()
        key = (ev.get("agent_id", "unknown"), window_start)
        groups.setdefault(key, []).append(ev)

    chunks: list[Chunk] = []
    for (agent_id, window_start_iso), group in groups.items():
        window_start_dt = datetime.fromisoformat(window_start_iso)
        window_end_iso = (window_start_dt + timedelta(minutes=window_minutes)).isoformat()
        group_sorted = sorted(group, key=lambda e: e.get("id") or 0)
        event_ids = [e["id"] for e in group_sorted if e.get("id") is not None]
        states_seen = [e["state"] for e in group_sorted if e.get("state")]
        chunks.append(Chunk(
            chunk_id=f"{agent_id}|{window_start_iso}",
            agent_id=agent_id,
            window_start=window_start_iso,
            window_end=window_end_iso,
            event_count=len(group_sorted),
            summary=summarize_chunk(group_sorted),
            event_ids=event_ids,
            states_seen=states_seen,
        ))

    chunks.sort(key=lambda c: (c.window_start, c.agent_id))
    return chunks


# ----------------------------------------------------------------------------
# Vector store (ChromaDB)
# ----------------------------------------------------------------------------
class VectorIndex:
    """Persistent ChromaDB wrapper. Chunk text -> document, fields -> metadata.

    ChromaDB metadata must be scalar (str/int/float/bool), so the list-valued
    fields (event_ids, states_seen) are stored as JSON strings and parsed back.
    """

    def __init__(self, persist_dir: str, collection_name: str = "agent_activity"):
        import chromadb
        from chromadb.config import Settings

        os.makedirs(persist_dir, exist_ok=True)
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self._client = chromadb.PersistentClient(
            path=persist_dir,
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(name=collection_name)

    def upsert_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if not chunks:
            return
        ids = [c.chunk_id for c in chunks]
        documents = [c.summary for c in chunks]
        metadatas = [{
            "agent_id": c.agent_id,
            "window_start": c.window_start,
            "window_end": c.window_end,
            "event_count": c.event_count,
            "event_ids": json.dumps(c.event_ids),
            "states_seen": json.dumps(c.states_seen),
        } for c in chunks]
        self._collection.upsert(
            ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas,
        )

    def query(self, query_embedding: list[float], n_results: int = 5,
              where: Optional[dict] = None) -> list[dict]:
        res = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where,
        )
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]

        out = []
        for i, chunk_id in enumerate(ids):
            meta = dict(metas[i]) if i < len(metas) and metas[i] else {}
            for list_field in ("event_ids", "states_seen"):
                if isinstance(meta.get(list_field), str):
                    try:
                        meta[list_field] = json.loads(meta[list_field])
                    except (ValueError, TypeError):
                        pass
            out.append({
                "chunk_id": chunk_id,
                "summary": docs[i] if i < len(docs) else None,
                "metadata": meta,
                "distance": dists[i] if i < len(dists) else None,
            })
        return out

    def count(self) -> int:
        return self._collection.count()

    def delete_collection(self) -> None:
        self._client.delete_collection(self.collection_name)


# ----------------------------------------------------------------------------
# Index progress state
# ----------------------------------------------------------------------------
@dataclass
class IndexState:
    path: str
    last_indexed_event_id: int = 0
    last_run_at: Optional[str] = None
    total_chunks: int = 0

    @classmethod
    def load(cls, path: str) -> "IndexState":
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls(
                path=path,
                last_indexed_event_id=int(data.get("last_indexed_event_id", 0)),
                last_run_at=data.get("last_run_at"),
                total_chunks=int(data.get("total_chunks", 0)),
            )
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError, TypeError):
            return cls(path=path)

    def save(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        data = {
            "last_indexed_event_id": self.last_indexed_event_id,
            "last_run_at": self.last_run_at,
            "total_chunks": self.total_chunks,
        }
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, self.path)


# ----------------------------------------------------------------------------
# Orchestrator
# ----------------------------------------------------------------------------
def run_index_pass(
    activity_db_path: str,
    vector_dir: str,
    embedding_service: EmbeddingService,
    state: IndexState,
    window_minutes: int = 15,
) -> dict:
    """Run ONE append-only indexing pass; returns stats.

    Reads events with id > state.last_indexed_event_id, chunks + embeds them,
    upserts into the vector index, and advances the state.
    """
    start = time.monotonic()

    # Point activity_log at the requested DB (idempotent). See smell note: this
    # is needed because activity_log keys off a module-level _DB_PATH.
    activity_log.init_db(activity_db_path)

    new_events = activity_log.get_events_since_id(
        state.last_indexed_event_id, limit=activity_log.MAX_LIMIT,
    )

    if not new_events:
        state.last_run_at = datetime.now(timezone.utc).isoformat()
        state.save()
        return {"new_events": 0, "new_chunks": 0,
                "duration_ms": int((time.monotonic() - start) * 1000)}

    chunks = chunk_events(new_events, window_minutes=window_minutes)
    if chunks:
        embeddings = embedding_service.embed_texts([c.summary for c in chunks])
        VectorIndex(vector_dir).upsert_chunks(chunks, embeddings)

    state.last_indexed_event_id = max(e["id"] for e in new_events)
    state.last_run_at = datetime.now(timezone.utc).isoformat()
    state.total_chunks += len(chunks)
    state.save()

    return {"new_events": len(new_events), "new_chunks": len(chunks),
            "duration_ms": int((time.monotonic() - start) * 1000)}
