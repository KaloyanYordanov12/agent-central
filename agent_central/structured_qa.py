"""Structured (non-vector) answering for the Secretary: the hybrid-retrieval path.

Pure vector RAG is structurally bad at counting and recency: it retrieves
semantically-similar chunks, not the newest row or ALL matching rows. So for
count / recency / aggregation questions we answer DIRECTLY from the activity_log
with SQL-style queries, grounding the answer in the real rows used (real
timestamps + agents) so the cited sources verify against the DB. Semantic
questions are left to the vector path (this module returns None for them).

Everything here is computed from the database, so it is deterministic and testable
with no LLM call ($0). It never fabricates: when the data genuinely has no answer,
it says so honestly.
"""
import logging
import sqlite3
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Agent name synonyms accepted in a question, and the display name used in answers.
_AGENT_SYNONYMS = {
    "deal_hunter": ("deal hunter", "deal_hunter", "dealhunter"),
    "job_scout": ("job scout", "job_scout"),
    "job_analyst": ("job analyst", "job_analyst"),
    "secretary": ("secretary",),
    "evaluator": ("evaluator",),
}
_AGENT_DISPLAY = {
    "deal_hunter": "Deal Hunter", "job_scout": "Job Scout",
    "job_analyst": "Job Analyst", "secretary": "Secretary", "evaluator": "Evaluator",
}

# Keywords that indicate a recency / count question (the structured-path triggers).
_RECENCY_MARKERS = ("most recent", "latest", "current state", "currently",
                    "right now", "most recently", "last state", "last event",
                    "last activity")
_COUNT_MARKERS = ("how many", "number of", "count of", "how often")
# Verbs that map to an agent's work "pass" (logged as a state_change to 'scanning').
_PASS_MARKERS = ("pass", "passes", "scan", "scanning", "scoring", "cycle", "run")


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _detect_agent(q):
    """Return the agent_id whose synonym appears in the question (longest match)."""
    best, best_len = None, -1
    for agent_id, syns in _AGENT_SYNONYMS.items():
        for s in syns:
            if s in q and len(s) > best_len:
                best, best_len = agent_id, len(s)
    return best


def _detect_window(q):
    """Return (since_iso_or_None, human_label) for a time window in the question."""
    now = datetime.now(timezone.utc)
    if "today" in q:
        return now.date().isoformat() + "T00:00:00+00:00", "today"
    if "this week" in q or "past week" in q or "last 7 days" in q or "this week" in q:
        return (now - timedelta(days=7)).isoformat(), "in the last 7 days"
    return None, "so far"


def _src(agent_id, ts):
    """A source that verifies against the DB: a 1-second window holding this event."""
    try:
        we = (datetime.fromisoformat(ts) + timedelta(seconds=1)).isoformat()
    except (ValueError, TypeError):
        we = ts
    return {"chunk_id": f"{agent_id}|{ts}", "agent_id": agent_id,
            "window_start": ts, "window_end": we, "score": 1.0}


def _result(answer, sources):
    return {"answer": answer, "sources": sources, "model": None,
            "input_tokens": 0, "output_tokens": 0, "path": "structured"}


def _no_data():
    # Honest abstention phrasing when the data truly has nothing.
    return _result("Based on the activity log, I don't have any matching events "
                   "recorded for that.", [])


def structured_answer(question, db_path):
    """Answer count/recency/aggregation questions from the DB, else return None.

    None means "let the vector path handle this" (semantic questions), so the
    existing semantic Q&A is never regressed.
    """
    if not db_path or not question:
        return None
    q = " ".join(question.lower().split())
    agent = _detect_agent(q)
    since, win_label = _detect_window(q)
    is_recency = any(m in q for m in _RECENCY_MARKERS)
    is_count = any(m in q for m in _COUNT_MARKERS)
    # Aggregation only on the plural "agents" + an activity word, so a single-agent
    # semantic question ("what has Deal Hunter been doing") is NOT captured here.
    asks_active_agents = ("agents" in q) and any(
        k in q for k in ("active", "been active", "working", "running", "doing", "have been"))

    try:
        if is_recency:
            res = _answer_recency(q, agent, db_path)
            if res:
                return res
        if is_count:
            res = _answer_count(q, agent, since, win_label, db_path)
            if res:
                return res
        if asks_active_agents:
            return _answer_active_agents(since, win_label, db_path)
    except Exception:
        logger.exception("structured_answer failed; falling back to vector path")
        return None
    return None


def _answer_recency(q, agent, db_path):
    conn = _connect(db_path)
    try:
        wants_agent_of_event = ("which agent" in q or "what agent" in q or "who" in q)
        # "Which agent logged the most recent event?" -> the most recent event overall.
        if wants_agent_of_event and "event" in q:
            row = conn.execute(
                "SELECT agent_id, event_type, state, timestamp FROM activity_log "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if not row:
                return _no_data()
            disp = _AGENT_DISPLAY.get(row["agent_id"], row["agent_id"])
            st = f" ({row['state']})" if row["state"] else ""
            return _result(
                f"{disp} logged the most recent activity event{st}: a "
                f"{row['event_type']} at {row['timestamp']}.",
                [_src(row["agent_id"], row["timestamp"])])
        # "Most recent state of <agent>?"
        if agent:
            row = conn.execute(
                "SELECT state, timestamp FROM activity_log WHERE agent_id = ? "
                "AND event_type IN ('state_change', 'error') AND state IS NOT NULL "
                "ORDER BY id DESC LIMIT 1", (agent,)
            ).fetchone()
            disp = _AGENT_DISPLAY.get(agent, agent)
            if not row:
                return _result(
                    f"The activity log has no recorded state for {disp} yet.", [])
            return _result(
                f"The most recent state recorded for {disp} is {row['state']}, "
                f"as of {row['timestamp']}.", [_src(agent, row["timestamp"])])
        # Generic "most recent event".
        if "event" in q or "activity" in q:
            row = conn.execute(
                "SELECT agent_id, event_type, state, timestamp FROM activity_log "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if not row:
                return _no_data()
            disp = _AGENT_DISPLAY.get(row["agent_id"], row["agent_id"])
            st = f" ({row['state']})" if row["state"] else ""
            return _result(
                f"The most recent activity event was logged by {disp}{st}: a "
                f"{row['event_type']} at {row['timestamp']}.",
                [_src(row["agent_id"], row["timestamp"])])
    finally:
        conn.close()
    return None


def _answer_count(q, agent, since, win_label, db_path):
    conn = _connect(db_path)
    try:
        wsql, params = "", []
        if since:
            wsql, params = " AND timestamp >= ?", [since]

        if "error" in q:
            rows = conn.execute(
                "SELECT agent_id, timestamp FROM activity_log "
                "WHERE event_type = 'error'" + wsql + " ORDER BY id DESC", params
            ).fetchall()
            n = len(rows)
            if n == 0:
                return _result(f"0 errors were logged {win_label} (no errors recorded).", [])
            return _result(
                f"{n} error{'s' if n != 1 else ''} were logged {win_label}.",
                [_src(r["agent_id"], r["timestamp"]) for r in rows[:5]])

        # "How many times did <agent> run / scan / start a pass?" -> scanning passes.
        if agent and any(k in q for k in _PASS_MARKERS):
            rows = conn.execute(
                "SELECT timestamp FROM activity_log WHERE agent_id = ? "
                "AND event_type = 'state_change' AND state = 'scanning'" + wsql +
                " ORDER BY id DESC", [agent] + params
            ).fetchall()
            n = len(rows)
            disp = _AGENT_DISPLAY.get(agent, agent)
            return _result(
                f"{disp} started {n} scoring pass{'es' if n != 1 else ''} {win_label}.",
                [_src(agent, r["timestamp"]) for r in rows[:5]])

        # Generic event count (optionally for one agent).
        if "event" in q or "activity" in q:
            base = "SELECT agent_id, timestamp FROM activity_log WHERE 1 = 1"
            p = []
            if agent:
                base += " AND agent_id = ?"
                p.append(agent)
            if since:
                base += " AND timestamp >= ?"
                p.append(since)
            rows = conn.execute(base + " ORDER BY id DESC", p).fetchall()
            n = len(rows)
            who = (_AGENT_DISPLAY.get(agent, agent) + " logged ") if agent else ""
            return _result(
                f"{who}{n} activity event{'s' if n != 1 else ''} {win_label}.",
                [_src(r["agent_id"], r["timestamp"]) for r in rows[:5]])
    finally:
        conn.close()
    return None


def _answer_active_agents(since, win_label, db_path):
    conn = _connect(db_path)
    try:
        clause = " WHERE timestamp >= ?" if since else ""
        params = [since] if since else []
        rows = conn.execute(
            "SELECT DISTINCT agent_id FROM activity_log" + clause + " ORDER BY agent_id",
            params,
        ).fetchall()
        agents = [r["agent_id"] for r in rows]
        if not agents:
            return _result(f"No agents have logged any activity {win_label}.", [])
        disp = [_AGENT_DISPLAY.get(a, a) for a in agents]
        sources = []
        for a in agents:
            r = conn.execute(
                "SELECT timestamp FROM activity_log WHERE agent_id = ?" +
                (" AND timestamp >= ?" if since else "") + " ORDER BY id DESC LIMIT 1",
                [a] + ([since] if since else []),
            ).fetchone()
            if r:
                sources.append(_src(a, r["timestamp"]))
        return _result(
            f"{len(disp)} agent{'s' if len(disp) != 1 else ''} have been active "
            f"{win_label}: " + ", ".join(disp) + ".", sources)
    finally:
        conn.close()
