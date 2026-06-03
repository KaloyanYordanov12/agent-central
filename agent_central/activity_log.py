"""
Durable activity logging for Agent Central — foundation for the Secretary agent.

Persists agent state changes, lifecycle events, and errors to a SQLite database
so history can be queried later. Standard library only (sqlite3 + json), no new
dependencies.

The active DB path is module-level state set by init_db(); log_event/query_events/
get_event_count operate against it. (See the production-smell note in the commit
message — this module-level path is intentional for now, not a clean design.)
"""
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

# Default DB lives at <project root>/data/activity.db. init_db() can override it
# (e.g. tests point it at a tmp file).
DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "activity.db",
)
_DB_PATH = DEFAULT_DB_PATH

MAX_LIMIT = 1000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    state TEXT,
    payload TEXT,
    metadata TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_id ON activity_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_timestamp ON activity_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_event_type ON activity_log(event_type);

-- Job Scout (commit 1): discovered job listings, deduped by URL. Lives in the
-- same DB file as activity_log; created here so init_db sets up both tables.
CREATE TABLE IF NOT EXISTS discovered_jobs (
    url TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT,
    location TEXT,
    description TEXT,
    posted_at TEXT,
    discovered_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'discovered',
    filter_reason TEXT,
    payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_dj_status ON discovered_jobs(status);
CREATE INDEX IF NOT EXISTS idx_dj_source ON discovered_jobs(source);
CREATE INDEX IF NOT EXISTS idx_dj_discovered_at ON discovered_jobs(discovered_at);
"""


def init_db(db_path: str) -> None:
    """Create the DB file + schema if missing and set it as the active path.

    Idempotent — safe to call on every startup.
    """
    global _DB_PATH
    _DB_PATH = db_path
    parent = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def log_event(
    agent_id: str,
    event_type: str,
    state: Optional[str] = None,
    payload: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> int:
    """Insert a new event row and return its id.

    payload/metadata are stored as JSON strings (or NULL). Timestamp is set to
    the current UTC time in ISO 8601 format.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    payload_json = json.dumps(payload) if payload is not None else None
    metadata_json = json.dumps(metadata) if metadata is not None else None
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO activity_log "
            "(timestamp, agent_id, event_type, state, payload, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (timestamp, agent_id, event_type, state, payload_json, metadata_json),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def record_state_change(
    agent_id: str,
    new_state: Optional[str],
    prev_state: Optional[str] = None,
    payload: Optional[dict] = None,
) -> Optional[int]:
    """Log a 'state_change' event only if the state actually changed.

    Returns the new row id, or None when new_state == prev_state (nothing written).
    This is the single decision point for state-change logging; the poller calls
    it inline at its existing state-change site so we never log on unchanged polls.
    """
    if new_state == prev_state:
        return None
    return log_event(
        agent_id,
        "state_change",
        state=new_state,
        payload=payload,
        metadata={"previous_state": prev_state},
    )


def query_events(
    agent_id: Optional[str] = None,
    event_type: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Return matching events as dicts (payload/metadata parsed), newest first.

    `limit` is capped at 1000. `since`/`until` are ISO 8601 strings compared
    lexically against the stored timestamps (same format -> correct ordering).
    """
    limit = max(0, min(limit, MAX_LIMIT))
    offset = max(0, offset)

    clauses, params = [], []
    if agent_id is not None:
        clauses.append("agent_id = ?")
        params.append(agent_id)
    if event_type is not None:
        clauses.append("event_type = ?")
        params.append(event_type)
    if since is not None:
        clauses.append("timestamp >= ?")
        params.append(since)
    if until is not None:
        clauses.append("timestamp <= ?")
        params.append(until)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

    sql = (
        "SELECT id, timestamp, agent_id, event_type, state, payload, metadata "
        "FROM activity_log" + where +
        " ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?"
    )
    params.extend([limit, offset])

    conn = _connect()
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    events = []
    for r in rows:
        events.append({
            "id": r["id"],
            "timestamp": r["timestamp"],
            "agent_id": r["agent_id"],
            "event_type": r["event_type"],
            "state": r["state"],
            "payload": json.loads(r["payload"]) if r["payload"] else None,
            "metadata": json.loads(r["metadata"]) if r["metadata"] else None,
        })
    return events


def get_event_count(agent_id: Optional[str] = None) -> int:
    """Return the number of events, optionally filtered by agent_id."""
    if agent_id is not None:
        sql, params = "SELECT COUNT(*) FROM activity_log WHERE agent_id = ?", (agent_id,)
    else:
        sql, params = "SELECT COUNT(*) FROM activity_log", ()
    conn = _connect()
    try:
        return int(conn.execute(sql, params).fetchone()[0])
    finally:
        conn.close()


def get_events_since_id(last_id: int, limit: int = MAX_LIMIT) -> list[dict]:
    """Return events with id > last_id, ASCENDING by id (chronological insert order).

    Used by the background indexer for append-only consumption: pass the last
    indexed row id, get the next batch in order. `limit` is capped at 1000.
    """
    limit = max(0, min(limit, MAX_LIMIT))
    sql = (
        "SELECT id, timestamp, agent_id, event_type, state, payload, metadata "
        "FROM activity_log WHERE id > ? ORDER BY id ASC LIMIT ?"
    )
    conn = _connect()
    try:
        rows = conn.execute(sql, (last_id, limit)).fetchall()
    finally:
        conn.close()

    events = []
    for r in rows:
        events.append({
            "id": r["id"],
            "timestamp": r["timestamp"],
            "agent_id": r["agent_id"],
            "event_type": r["event_type"],
            "state": r["state"],
            "payload": json.loads(r["payload"]) if r["payload"] else None,
            "metadata": json.loads(r["metadata"]) if r["metadata"] else None,
        })
    return events
