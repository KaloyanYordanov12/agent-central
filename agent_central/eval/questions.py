"""Fixed Secretary groundedness question set + DB-computed ground truth.

The TRUTH for every question here is computed directly from the SQLite
activity_log with code (the truth_fn), never from a model. This is the objective,
no-labeling ground truth from the build spec: the database IS the ground truth,
which is strictly stronger than any model's opinion and immune to the one real
risk of stronger-model-as-judge (Opus and Haiku are both Claude and could share
a blind spot).

Each question is answerable from the same activity_log events the Secretary's
vector index is built from, so a grounded Secretary CAN get them right; when it
does not, that is a real, honestly-measured groundedness miss.
"""
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

PROVENANCE = "computed from activity_log"

# Display synonyms accepted when matching an agent mention in a free-text answer.
# An answer may say "Job Scout" or "job_scout"; either counts as mentioning it.
AGENT_SYNONYMS = {
    "deal_hunter": ["deal hunter", "deal_hunter"],
    "job_scout": ["job scout", "job_scout"],
    "job_analyst": ["job analyst", "job_analyst"],
    "secretary": ["secretary"],
    "evaluator": ["evaluator"],
}


@dataclass
class GroundednessQuestion:
    """One objective question. truth_fn(db_path) computes the answer from the DB.

    kind:
      'count'    -> truth is an int; the answer must state that integer
                    (or, when the truth is 0, negate the existence honestly).
      'contains' -> truth is a list of synonym-groups; the answer must mention at
                    least one synonym from every group (an empty list means the
                    honest answer is "none / I don't have that").
    """
    id: str
    text: str
    kind: str
    truth_fn: Callable
    provenance: str = PROVENANCE


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _agent_group(agent_id: str) -> list:
    """Synonyms for one agent_id (falls back to the raw id for unknown agents)."""
    return AGENT_SYNONYMS.get(agent_id, [agent_id])


# ----------------------------------------------------------------------------
# Truth functions — each reads the real activity_log and returns the true answer.
# ----------------------------------------------------------------------------
def truth_agents_active_today(db_path: str) -> list:
    """Synonym-groups for every distinct agent with an event logged today (UTC)."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT agent_id FROM activity_log "
            "WHERE substr(timestamp, 1, 10) = ? ORDER BY agent_id",
            (_today(),),
        ).fetchall()
    finally:
        conn.close()
    return [_agent_group(r["agent_id"]) for r in rows]


def truth_errors_today(db_path: str) -> int:
    """Count of error events logged across all agents today (UTC)."""
    conn = _connect(db_path)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM activity_log "
            "WHERE event_type = 'error' AND substr(timestamp, 1, 10) = ?",
            (_today(),),
        ).fetchone()[0]
    finally:
        conn.close()
    return int(n)


def _recent_state(db_path: str, agent_id: str) -> list:
    """Synonym-group ([[state]]) for an agent's most recent state, else []."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT state FROM activity_log WHERE agent_id = ? "
            "AND event_type IN ('state_change', 'error') AND state IS NOT NULL "
            "ORDER BY id DESC LIMIT 1",
            (agent_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row or not row["state"]:
        return []
    return [[str(row["state"]).lower()]]


def truth_job_scout_recent_state(db_path: str) -> list:
    return _recent_state(db_path, "job_scout")


def truth_job_analyst_recent_state(db_path: str) -> list:
    return _recent_state(db_path, "job_analyst")


def truth_most_recent_event_agent(db_path: str) -> list:
    """Synonym-group for the agent that logged the single most recent event."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT agent_id FROM activity_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return []
    return [_agent_group(row["agent_id"])]


def truth_job_analyst_passes_today(db_path: str) -> int:
    """How many scoring passes the Job Analyst started today (state 'scanning')."""
    conn = _connect(db_path)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM activity_log WHERE agent_id = 'job_analyst' "
            "AND event_type = 'state_change' AND state = 'scanning' "
            "AND substr(timestamp, 1, 10) = ?",
            (_today(),),
        ).fetchone()[0]
    finally:
        conn.close()
    return int(n)


# The fixed, version-controlled question set. Order is stable for reproducibility.
GROUNDEDNESS_QUESTIONS = [
    GroundednessQuestion(
        id="agents_active_today",
        text="Which agents have been active today?",
        kind="contains",
        truth_fn=truth_agents_active_today,
    ),
    GroundednessQuestion(
        id="errors_today",
        text="How many errors were logged across all agents today?",
        kind="count",
        truth_fn=truth_errors_today,
    ),
    GroundednessQuestion(
        id="job_scout_recent_state",
        text="What is the most recent state recorded for the Job Scout?",
        kind="contains",
        truth_fn=truth_job_scout_recent_state,
    ),
    GroundednessQuestion(
        id="job_analyst_recent_state",
        text="What is the most recent state recorded for the Job Analyst?",
        kind="contains",
        truth_fn=truth_job_analyst_recent_state,
    ),
    GroundednessQuestion(
        id="most_recent_event_agent",
        text="Which agent logged the most recent activity event?",
        kind="contains",
        truth_fn=truth_most_recent_event_agent,
    ),
    GroundednessQuestion(
        id="job_analyst_passes_today",
        text="How many times did the Job Analyst start a scoring pass today?",
        kind="count",
        truth_fn=truth_job_analyst_passes_today,
    ),
]
