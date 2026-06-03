"""Tests for the commit-2b read-only jobs/cost endpoints.

Use the TestClient + temp_activity_db fixtures (from conftest). The endpoints
read activity_log._DB_PATH, which temp_activity_db points at a tmp file, so rows
inserted into that file are what the endpoints return.
"""
import sqlite3
from datetime import datetime, timezone, timedelta


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def _yesterday():
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


def _insert_job(db, url, **kw):
    cols = {
        "url": url, "source": "remotive", "title": "Engineer", "company": "Acme",
        "location": "Remote", "description": "d", "posted_at": None,
        "discovered_at": _today() + "T10:00:00+00:00", "status": "discovered",
        "filter_reason": None, "payload": "{}", "llm_score": None,
        "llm_reasoning": None, "llm_red_flags": None, "notified_at": None,
    }
    cols.update(kw)
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO discovered_jobs (url, source, title, company, location, "
            "description, posted_at, discovered_at, status, filter_reason, payload, "
            "llm_score, llm_reasoning, llm_red_flags, notified_at) VALUES "
            "(:url,:source,:title,:company,:location,:description,:posted_at,"
            ":discovered_at,:status,:filter_reason,:payload,:llm_score,:llm_reasoning,"
            ":llm_red_flags,:notified_at)",
            cols,
        )
        conn.commit()
    finally:
        conn.close()


def _insert_llm_call(db, agent_id="job_analyst", model="claude-haiku-4-5",
                     cost=0.001, timestamp=None):
    ts = timestamp or (_today() + "T10:00:00+00:00")
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO llm_calls (timestamp, agent_id, model, purpose, input_tokens, "
            "output_tokens, cache_creation_tokens, cache_read_tokens, estimated_cost_usd, "
            "duration_ms, ok, error, metadata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts, agent_id, model, "score_job", 100, 20, 0, 0, cost, 50, 1, None, None),
        )
        conn.commit()
    finally:
        conn.close()


# --- /api/jobs/discovered -----------------------------------------------------

def test_jobs_discovered_returns_empty_when_no_jobs(client, temp_activity_db):
    data = client.get("/api/jobs/discovered").json()
    assert data["jobs"] == []
    assert data["stats_by_status"] == {}
    assert data["stats_by_source"] == {}


def test_jobs_discovered_returns_recent_first(client, temp_activity_db):
    for i in range(5):
        _insert_job(temp_activity_db, f"u{i}",
                    discovered_at=_today() + f"T10:0{i}:00+00:00")
    jobs = client.get("/api/jobs/discovered").json()["jobs"]
    assert [j["url"] for j in jobs] == ["u4", "u3", "u2", "u1", "u0"]


def test_jobs_discovered_filters_by_source(client, temp_activity_db):
    _insert_job(temp_activity_db, "a", source="aijobs")
    _insert_job(temp_activity_db, "b", source="remotive")
    _insert_job(temp_activity_db, "c", source="remoteok")
    jobs = client.get("/api/jobs/discovered", params={"source": "remotive"}).json()["jobs"]
    assert len(jobs) == 1 and jobs[0]["source"] == "remotive"


def test_jobs_discovered_filters_by_status(client, temp_activity_db):
    _insert_job(temp_activity_db, "a", status="discovered")
    _insert_job(temp_activity_db, "b", status="scored", llm_score=80)
    jobs = client.get("/api/jobs/discovered", params={"status": "scored"}).json()["jobs"]
    assert len(jobs) == 1 and jobs[0]["status"] == "scored"


def test_jobs_discovered_respects_limit(client, temp_activity_db):
    for i in range(60):
        _insert_job(temp_activity_db, f"u{i}",
                    discovered_at=_today() + f"T10:{i:02d}:00+00:00")
    jobs = client.get("/api/jobs/discovered", params={"limit": 10}).json()["jobs"]
    assert len(jobs) == 10


def test_jobs_discovered_caps_limit_at_200(client, temp_activity_db):
    _insert_job(temp_activity_db, "u1")
    resp = client.get("/api/jobs/discovered", params={"limit": 99999})
    assert resp.status_code == 200
    assert len(resp.json()["jobs"]) <= 200


def test_jobs_discovered_stats_are_accurate(client, temp_activity_db):
    for i in range(3):
        _insert_job(temp_activity_db, f"d{i}", status="discovered")
    for i in range(2):
        _insert_job(temp_activity_db, f"s{i}", status="scored", llm_score=70)
    _insert_job(temp_activity_db, "n0", status="notified", llm_score=90)
    for i in range(5):
        _insert_job(temp_activity_db, f"r{i}", status="rejected_by_filter")
    stats = client.get("/api/jobs/discovered").json()["stats_by_status"]
    assert stats["discovered"] == 3
    assert stats["scored"] == 2
    assert stats["notified"] == 1
    assert stats["rejected_by_filter"] == 5


# --- /api/jobs/analyst-activity ----------------------------------------------

def test_analyst_activity_returns_recent_scored_jobs(client, temp_activity_db):
    _insert_job(temp_activity_db, "s1", status="scored", llm_score=80,
                discovered_at=_today() + "T10:00:00+00:00", llm_reasoning="good fit")
    _insert_job(temp_activity_db, "s2", status="scored", llm_score=60,
                discovered_at=_today() + "T11:00:00+00:00")
    _insert_job(temp_activity_db, "unscored", status="discovered")  # no llm_score
    data = client.get("/api/jobs/analyst-activity").json()
    scores = data["recent_scores"]
    assert len(scores) == 2                  # only scored jobs
    assert scores[0]["url"] == "s2"          # most recent first
    assert scores[0]["score"] == 60


def test_analyst_activity_summary_calculates_today_only(client, temp_activity_db):
    _insert_job(temp_activity_db, "t1", status="scored", llm_score=80,
                discovered_at=_today() + "T09:00:00+00:00")
    _insert_job(temp_activity_db, "t2", status="notified", llm_score=90,
                discovered_at=_today() + "T10:00:00+00:00",
                notified_at=_today() + "T10:01:00+00:00")
    _insert_job(temp_activity_db, "y1", status="scored", llm_score=40,
                discovered_at=_yesterday() + "T10:00:00+00:00")
    summary = client.get("/api/jobs/analyst-activity").json()["summary"]
    assert summary["scored_today"] == 2          # excludes yesterday's y1
    assert summary["notified_today"] == 1
    assert summary["top_score_today"] == 90


# --- /api/llm-costs/today -----------------------------------------------------

def test_llm_costs_today_zero_when_no_calls(client, temp_activity_db):
    data = client.get("/api/llm-costs/today").json()
    assert data["total_usd"] == 0
    assert data["call_count"] == 0
    assert data["by_agent"] == {}
    assert data["by_model"] == {}


def test_llm_costs_today_aggregates_correctly(client, temp_activity_db):
    _insert_llm_call(temp_activity_db, "job_analyst", "claude-haiku-4-5", 0.002)
    _insert_llm_call(temp_activity_db, "job_analyst", "claude-haiku-4-5", 0.003)
    _insert_llm_call(temp_activity_db, "secretary", "claude-haiku-4-5", 0.001)
    _insert_llm_call(temp_activity_db, "secretary", "claude-haiku-4-5", 0.0005)
    _insert_llm_call(temp_activity_db, "job_analyst", "claude-haiku-4-5", 0.0015)
    data = client.get("/api/llm-costs/today").json()
    assert data["call_count"] == 5
    assert abs(data["total_usd"] - 0.008) < 1e-9
    assert abs(data["by_agent"]["job_analyst"] - 0.0065) < 1e-9
    assert abs(data["by_agent"]["secretary"] - 0.0015) < 1e-9
    assert abs(data["by_model"]["claude-haiku-4-5"] - 0.008) < 1e-9


def test_llm_costs_today_excludes_yesterday(client, temp_activity_db):
    _insert_llm_call(temp_activity_db, cost=0.01, timestamp=_yesterday() + "T10:00:00+00:00")
    _insert_llm_call(temp_activity_db, cost=0.02, timestamp=_yesterday() + "T11:00:00+00:00")
    _insert_llm_call(temp_activity_db, cost=0.003, timestamp=_today() + "T10:00:00+00:00")
    data = client.get("/api/llm-costs/today").json()
    assert data["call_count"] == 1
    assert abs(data["total_usd"] - 0.003) < 1e-9
