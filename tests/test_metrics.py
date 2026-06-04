"""Tests for the read-only metrics module + /api/metrics endpoint."""
import sqlite3
from datetime import datetime, timezone, timedelta

from agent_central import metrics


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def _ts(h=10, m=0, s=0, day=None):
    d = day or _today()
    return f"{d}T{h:02d}:{m:02d}:{s:02d}+00:00"


def _llm(db, agent="job_analyst", model="claude-haiku-4-5", ok=1, tin=100, tout=20,
         cost=0.001, dur=50, ts=None):
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO llm_calls (timestamp, agent_id, model, purpose, input_tokens, "
            "output_tokens, cache_creation_tokens, cache_read_tokens, estimated_cost_usd, "
            "duration_ms, ok, error, metadata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts or _ts(), agent, model, "score_job", tin, tout, 0, 0, cost, dur, ok,
             None if ok else "boom", None),
        )
        conn.commit()
    finally:
        conn.close()


def _evt(db, agent="deal_hunter", etype="state_change", state="scanning", ts=None):
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO activity_log (timestamp, agent_id, event_type, state, payload, metadata) "
            "VALUES (?,?,?,?,?,?)",
            (ts or _ts(), agent, etype, state, None, None),
        )
        conn.commit()
    finally:
        conn.close()


def test_metrics_llm_totals_and_rates(client, temp_activity_db):
    db = temp_activity_db
    _llm(db, ok=1, tin=100, tout=20, cost=0.002, dur=40)
    _llm(db, ok=1, tin=200, tout=30, cost=0.003, dur=60)
    _llm(db, ok=0, tin=0, tout=0, cost=0.0, dur=10)
    data = metrics.compute_metrics(db, days=7)
    llm = data["llm"]
    assert llm["total"] == 3 and llm["ok"] == 2 and llm["error"] == 1
    assert abs(llm["success_rate"] - 0.6667) < 1e-3
    assert llm["tokens"] == {"input": 300, "output": 50}
    assert abs(llm["cost_usd"] - 0.005) < 1e-9
    assert llm["avg_latency_ms"] == 50  # mean of ok-call durations (40, 60)


def test_metrics_breakdowns_and_per_day(client, temp_activity_db):
    db = temp_activity_db
    _llm(db, agent="job_analyst", model="claude-haiku-4-5", ok=1)
    _llm(db, agent="secretary", model="claude-haiku-4-5", ok=1)
    _llm(db, agent="job_analyst", model="other-model", ok=0)
    data = metrics.compute_metrics(db, days=14)
    by_model = {m["name"]: m for m in data["llm"]["by_model"]}
    by_agent = {a["name"]: a for a in data["llm"]["by_agent"]}
    assert by_model["claude-haiku-4-5"]["calls"] == 2
    assert by_agent["job_analyst"]["calls"] == 2 and by_agent["job_analyst"]["error"] == 1
    assert len(data["llm"]["calls_per_day"]) == 14
    assert data["llm"]["calls_per_day"][-1]["ok"] == 2  # today
    assert data["llm"]["calls_per_day"][-1]["error"] == 1


def test_metrics_state_durations(client, temp_activity_db):
    db = temp_activity_db
    # deal_hunter: scanning at 10:00, idle at 10:05 -> 300s scanning
    _evt(db, "deal_hunter", "state_change", "scanning", ts=_ts(10, 0, 0))
    _evt(db, "deal_hunter", "state_change", "idle", ts=_ts(10, 5, 0))
    _evt(db, "deal_hunter", "state_change", "scanning", ts=_ts(10, 6, 0))  # idle lasted 60s
    data = metrics.compute_metrics(db, days=7)
    durs = {(d["agent"], d["state"]): d["seconds"] for d in data["activity"]["state_durations"]}
    assert durs[("deal_hunter", "scanning")] == 300
    assert durs[("deal_hunter", "idle")] == 60
    assert data["activity"]["total_events"] == 3
    assert data["activity"]["by_type"]["state_change"] == 3


def test_metrics_endpoint_shape(client, temp_activity_db):
    _llm(temp_activity_db, ok=1)
    _evt(temp_activity_db, "secretary", "state_change", "answering")
    data = client.get("/api/metrics?days=7").json()
    assert "llm" in data and "activity" in data
    assert data["window_days"] == 7
    assert data["llm"]["total"] == 1
    assert "by_model" in data["llm"] and "state_durations" in data["activity"]


def test_replay_timeline_ordered_state_events_only(client, temp_activity_db):
    db = temp_activity_db
    _evt(db, "deal_hunter", "state_change", "scanning", ts=_ts(10, 0, 0))
    _evt(db, "deal_hunter", "lifecycle", "online", ts=_ts(10, 1, 0))
    _evt(db, "job_scout", "state_change", "idle", ts=_ts(10, 2, 0))
    # a lifecycle event with no state must be excluded (state is None)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO activity_log (timestamp, agent_id, event_type, state) "
                 "VALUES (?,?,?,?)", (_ts(10, 3, 0), "job_scout", "lifecycle", None))
    conn.commit(); conn.close()
    data = client.get("/api/replay/timeline?days=7").json()
    assert data["count"] == 3  # the null-state row is excluded
    evs = data["events"]
    assert [e["state"] for e in evs] == ["scanning", "online", "idle"]  # oldest first
    assert all("agent_id" in e and "timestamp" in e for e in evs)


def test_metrics_empty_db_is_safe(client, temp_activity_db):
    data = client.get("/api/metrics").json()
    assert data["llm"]["total"] == 0 and data["llm"]["success_rate"] == 0
    assert data["activity"]["total_events"] == 0
    assert data["llm"]["calls_per_day"][-1]["ok"] == 0
