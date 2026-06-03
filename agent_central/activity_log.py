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
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

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

-- Job Analyst (commit 2a): per-LLM-call cost visibility.
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    model TEXT NOT NULL,
    purpose TEXT,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cache_creation_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    estimated_cost_usd REAL,
    duration_ms INTEGER,
    ok INTEGER NOT NULL DEFAULT 1,
    error TEXT,
    metadata TEXT
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_agent_id ON llm_calls(agent_id);
CREATE INDEX IF NOT EXISTS idx_llm_calls_timestamp ON llm_calls(timestamp);
CREATE INDEX IF NOT EXISTS idx_llm_calls_purpose ON llm_calls(purpose);
"""

# discovered_jobs columns added by Job Analyst (commit 2a). SQLite can't do
# "ADD COLUMN IF NOT EXISTS", so init_db adds these conditionally.
_DISCOVERED_JOBS_ADDED_COLUMNS = [
    ("llm_score", "ALTER TABLE discovered_jobs ADD COLUMN llm_score INTEGER"),
    ("llm_reasoning", "ALTER TABLE discovered_jobs ADD COLUMN llm_reasoning TEXT"),
    ("llm_red_flags", "ALTER TABLE discovered_jobs ADD COLUMN llm_red_flags TEXT"),
    ("notified_at", "ALTER TABLE discovered_jobs ADD COLUMN notified_at TEXT"),
]

# Approximate Anthropic pricing (USD per token) for cost estimation. Hardcoded —
# see the production-smell note: this won't track Anthropic price changes.
PRICING = {
    "claude-haiku-4-5": {"input": 0.80 / 1_000_000, "output": 4.00 / 1_000_000},
}


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
        # Additive migration: add Job Analyst columns to discovered_jobs if missing
        # (SQLite has no ADD COLUMN IF NOT EXISTS, so check PRAGMA table_info).
        existing = {row[1] for row in conn.execute("PRAGMA table_info(discovered_jobs)")}
        for column, alter_sql in _DISCOVERED_JOBS_ADDED_COLUMNS:
            if column not in existing:
                conn.execute(alter_sql)
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


def _estimate_cost_usd(model, input_tokens, output_tokens,
                       cache_creation_tokens, cache_read_tokens):
    """Estimate USD cost from token counts + PRICING. None if model unknown.

    Cache write ~= input rate x 1.25; cache read ~= input rate x 0.10 (approx).
    """
    pricing = PRICING.get(model)
    if pricing is None:
        logger.warning(f"[activity_log] no pricing for model '{model}'; cost left NULL")
        return None
    in_rate, out_rate = pricing["input"], pricing["output"]
    cost = (
        (input_tokens or 0) * in_rate
        + (output_tokens or 0) * out_rate
        + (cache_creation_tokens or 0) * in_rate * 1.25
        + (cache_read_tokens or 0) * in_rate * 0.10
    )
    return round(cost, 8)


def log_llm_call(agent_id, model, purpose, input_tokens, output_tokens,
                 cache_creation_tokens=0, cache_read_tokens=0,
                 duration_ms=None, ok=True, error=None, metadata=None) -> int:
    """Log an LLM call (tokens + estimated cost) to the llm_calls table.

    Returns the row id. estimated_cost_usd is computed from PRICING (NULL if the
    model isn't priced).
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    cost = _estimate_cost_usd(model, input_tokens, output_tokens,
                              cache_creation_tokens, cache_read_tokens)
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO llm_calls "
            "(timestamp, agent_id, model, purpose, input_tokens, output_tokens, "
            " cache_creation_tokens, cache_read_tokens, estimated_cost_usd, "
            " duration_ms, ok, error, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                timestamp, agent_id, model, purpose, input_tokens, output_tokens,
                cache_creation_tokens, cache_read_tokens, cost, duration_ms,
                1 if ok else 0, error,
                json.dumps(metadata) if metadata is not None else None,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def get_costs_today(db_path: Optional[str] = None) -> dict:
    """Aggregate today's (UTC) LLM spend from llm_calls for the cost indicator.

    Returns {date, total_usd, by_agent, by_model, call_count}. "Today" is the
    server's UTC calendar day (see the production-smell note).
    """
    db_path = db_path or _DB_PATH
    today = datetime.now(timezone.utc).date().isoformat()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT agent_id, model, estimated_cost_usd FROM llm_calls "
            "WHERE substr(timestamp, 1, 10) = ?",
            (today,),
        ).fetchall()
    finally:
        conn.close()

    by_agent, by_model, total, count = {}, {}, 0.0, 0
    for r in rows:
        count += 1
        cost = r["estimated_cost_usd"] or 0.0
        total += cost
        by_agent[r["agent_id"]] = round(by_agent.get(r["agent_id"], 0.0) + cost, 8)
        by_model[r["model"]] = round(by_model.get(r["model"], 0.0) + cost, 8)
    return {
        "date": today,
        "total_usd": round(total, 8),
        "by_agent": by_agent,
        "by_model": by_model,
        "call_count": count,
    }
