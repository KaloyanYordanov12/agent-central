"""Tests for Job Analyst (commit 2a) — scoring + notifications.

Hermetic: no real Anthropic calls (FakeJobAnalystClient), no real Discord posts
(httpx.post patched), real SQLite on tmp dirs.
"""
import sqlite3

import pytest

from agent_central import activity_log, job_analyst
from agent_central.job_analyst import Profile
from unittest.mock import patch


# --- fakes --------------------------------------------------------------------
class FakeJobAnalystClient:
    """Stand-in for JobAnalystClient.score_job — never hits the network."""

    def __init__(self, scores=None, score=80, model="claude-haiku-4-5", raise_exc=None):
        self.model = model
        self._scores = list(scores) if scores is not None else None
        self._default = score
        self._raise = raise_exc
        self.calls = []

    def score_job(self, profile_system_prompt, job):
        self.calls.append({"prompt": profile_system_prompt, "job": job})
        if self._raise:
            raise self._raise
        s = self._scores.pop(0) if self._scores else self._default
        return {
            "score": s, "reasoning": f"score is {s}", "fit_notes": {}, "red_flags": [],
            "usage": {"input_tokens": 100, "output_tokens": 20,
                      "cache_creation_tokens": 0, "cache_read_tokens": 50},
        }


class FakeHttpResp:
    def __init__(self, status=204):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _db(tmp_path):
    db = str(tmp_path / "activity.db")
    activity_log.init_db(db)
    return db


def _insert_job(db, url, title="Backend Engineer", status="discovered",
                source="remotive", description="A role", company="Acme",
                location="Remote", llm_score=None, notified_at=None,
                discovered_at="2026-06-02T10:00:00+00:00"):
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO discovered_jobs (url, source, title, company, location, "
            "description, posted_at, discovered_at, status, filter_reason, payload, "
            "llm_score, llm_reasoning, llm_red_flags, notified_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (url, source, title, company, location, description, None, discovered_at,
             status, None, "{}", llm_score, None, None, notified_at),
        )
        conn.commit()
    finally:
        conn.close()


def _rows(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return {r["url"]: dict(r) for r in conn.execute("SELECT * FROM discovered_jobs")}
    finally:
        conn.close()


# --- profile + prompt ---------------------------------------------------------

def test_load_profile_parses_yaml(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text(
        "name: Test Person\nbackground: builder\nlevel: Junior\n"
        "languages:\n  - Python\n  - Go\nstrict_no:\n  - Senior roles\n",
        encoding="utf-8",
    )
    profile = job_analyst.load_profile(str(p))
    assert profile.name == "Test Person"
    assert profile.level == "Junior"
    assert profile.languages == ["Python", "Go"]
    assert profile.strict_no == ["Senior roles"]


def test_build_system_prompt_includes_profile_fields():
    profile = Profile(
        name="Test Person", level="Entry / Junior",
        languages=["Python", "Rust"], frameworks=["FastAPI"],
        domains=["AI"], strict_no=["No senior roles", "No unpaid trials"],
    )
    prompt = job_analyst.build_system_prompt(profile)
    assert "Python" in prompt and "Rust" in prompt
    assert "Entry / Junior" in prompt
    assert "No senior roles" in prompt
    assert "No unpaid trials" in prompt


# --- llm_call logging + schema -----------------------------------------------

def test_llm_call_logging_inserts_row_with_cost(tmp_path):
    db = _db(tmp_path)
    activity_log.log_llm_call("job_analyst", "claude-haiku-4-5", "score_job",
                              input_tokens=1000, output_tokens=500)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM llm_calls").fetchone()
    finally:
        conn.close()
    assert row["agent_id"] == "job_analyst"
    assert row["input_tokens"] == 1000 and row["output_tokens"] == 500
    # 1000 * 0.80/1M + 500 * 4.00/1M = 0.0008 + 0.002 = 0.0028
    assert abs(row["estimated_cost_usd"] - 0.0028) < 1e-9
    assert row["ok"] == 1


def test_llm_call_logging_unknown_model_null_cost(tmp_path):
    _db(tmp_path)
    activity_log.log_llm_call("x", "some-unknown-model", "p", 100, 50)
    conn = sqlite3.connect(activity_log._DB_PATH)
    try:
        cost = conn.execute("SELECT estimated_cost_usd FROM llm_calls").fetchone()[0]
    finally:
        conn.close()
    assert cost is None


def test_schema_additions_idempotent(tmp_path):
    db = str(tmp_path / "a.db")
    activity_log.init_db(db)
    activity_log.init_db(db)  # second call must not error
    conn = sqlite3.connect(db)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(discovered_jobs)")}
    finally:
        conn.close()
    assert {"llm_score", "llm_reasoning", "llm_red_flags", "notified_at"}.issubset(cols)


# --- process_pending_jobs -----------------------------------------------------

def test_process_pending_jobs_scores_only_discovered_status(tmp_path):
    db = _db(tmp_path)
    _insert_job(db, "u1", status="discovered")
    _insert_job(db, "u2", status="rejected_by_filter")
    _insert_job(db, "u3", status="scored", llm_score=50)
    client = FakeJobAnalystClient(score=80)
    stats = job_analyst.process_pending_jobs(db, "PROMPT", client)
    assert stats["processed"] == 1
    assert {c["job"]["url"] for c in client.calls} == {"u1"}


def test_process_pending_jobs_updates_score_and_status(tmp_path):
    db = _db(tmp_path)
    _insert_job(db, "u1", status="discovered")
    client = FakeJobAnalystClient(score=85)
    job_analyst.process_pending_jobs(db, "PROMPT", client)
    row = _rows(db)["u1"]
    assert row["status"] == "scored"
    assert row["llm_score"] == 85
    assert row["llm_reasoning"]


def test_process_pending_jobs_low_score_rejected_by_llm(tmp_path):
    db = _db(tmp_path)
    _insert_job(db, "u1", status="discovered")
    client = FakeJobAnalystClient(score=10)  # below REJECT_FLOOR (25)
    job_analyst.process_pending_jobs(db, "PROMPT", client)
    assert _rows(db)["u1"]["status"] == "rejected_by_llm"


def test_process_pending_jobs_handles_client_error(tmp_path):
    db = _db(tmp_path)
    _insert_job(db, "u1", status="discovered")
    client = FakeJobAnalystClient(raise_exc=RuntimeError("api down"))
    stats = job_analyst.process_pending_jobs(db, "PROMPT", client)
    assert stats["errors"] == 1
    assert _rows(db)["u1"]["status"] == "discovered"  # untouched, retried later
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        call = conn.execute("SELECT * FROM llm_calls").fetchone()
    finally:
        conn.close()
    assert call["ok"] == 0
    assert "api down" in (call["error"] or "")


def test_is_fatal_config_error_classifies_credit_auth_vs_transient():
    cred = RuntimeError(
        "Error code: 400 - {'message': 'Your credit balance is too low to access "
        "the Anthropic API.'}")
    assert job_analyst._is_fatal_config_error(cred) is True
    assert job_analyst._is_fatal_config_error(Exception("authentication_error: x")) is True
    assert job_analyst._is_fatal_config_error(RuntimeError("api down")) is False
    assert job_analyst._is_fatal_config_error(Exception("Connection error.")) is False


def test_process_pending_jobs_aborts_pass_on_fatal_error(tmp_path):
    """F4: a credit/auth failure aborts the whole pass instead of failing every
    pending job one by one (which is what logged thousands of $0 calls)."""
    db = _db(tmp_path)
    for i in range(3):
        _insert_job(db, f"u{i}", discovered_at=f"2026-06-02T10:0{i}:00+00:00")
    fatal = RuntimeError("Error code: 400 - Your credit balance is too low")
    client = FakeJobAnalystClient(raise_exc=fatal)
    stats = job_analyst.process_pending_jobs(db, "PROMPT", client)
    assert stats["processed"] == 1            # aborted after the first failure
    assert stats["errors"] == 1
    assert stats["fatal_error"]               # surfaced for the caller to pause on
    assert len(client.calls) == 1             # did NOT hammer the remaining jobs
    assert all(r["status"] == "discovered" for r in _rows(db).values())


def test_process_pending_jobs_respects_max_per_run(tmp_path):
    db = _db(tmp_path)
    for i in range(30):
        _insert_job(db, f"u{i}", discovered_at=f"2026-06-02T10:{i:02d}:00+00:00")
    client = FakeJobAnalystClient(score=80)
    stats = job_analyst.process_pending_jobs(db, "PROMPT", client, max_per_run=5)
    assert stats["processed"] == 5
    assert len(client.calls) == 5


def test_description_bounded_to_4000_chars_before_send(tmp_path):
    db = _db(tmp_path)
    _insert_job(db, "u1", description="x" * 10000)
    client = FakeJobAnalystClient(score=80)
    job_analyst.process_pending_jobs(db, "PROMPT", client)
    sent_desc = client.calls[0]["job"]["description"]
    assert len(sent_desc) <= 4000


# --- notify_high_scores -------------------------------------------------------

def test_notify_high_scores_only_notifies_above_threshold(tmp_path):
    db = _db(tmp_path)
    for url, score in [("u60", 60), ("u75", 75), ("u80", 80), ("u95", 95)]:
        _insert_job(db, url, status="scored", llm_score=score)
    with patch.object(job_analyst.httpx, "post", return_value=FakeHttpResp()) as mock_post:
        stats = job_analyst.notify_high_scores(db, "https://webhook", threshold=75)
    assert stats["notified"] == 3
    assert mock_post.call_count == 3
    assert _rows(db)["u60"]["status"] == "scored"  # below threshold, untouched


def test_notify_high_scores_skips_already_notified(tmp_path):
    db = _db(tmp_path)
    _insert_job(db, "u1", status="scored", llm_score=90,
                notified_at="2026-06-02T11:00:00+00:00")
    with patch.object(job_analyst.httpx, "post", return_value=FakeHttpResp()) as mock_post:
        stats = job_analyst.notify_high_scores(db, "https://webhook", threshold=75)
    assert stats["notified"] == 0
    assert mock_post.call_count == 0


def test_notify_high_scores_handles_webhook_failure(tmp_path):
    db = _db(tmp_path)
    _insert_job(db, "u1", status="scored", llm_score=90)
    with patch.object(job_analyst.httpx, "post", side_effect=RuntimeError("network")):
        stats = job_analyst.notify_high_scores(db, "https://webhook", threshold=75)
    assert stats["errors"] == 1
    assert stats["notified"] == 0
    assert _rows(db)["u1"]["status"] == "scored"  # not marked notified


def test_notify_high_scores_skipped_when_no_webhook(tmp_path):
    db = _db(tmp_path)
    _insert_job(db, "u1", status="scored", llm_score=90)
    stats = job_analyst.notify_high_scores(db, None, threshold=75)  # no webhook
    assert stats["notified"] == 0
    assert stats["errors"] == 0


# --- run_analyst_pass ---------------------------------------------------------

def test_run_analyst_pass_full_flow(tmp_path):
    db = _db(tmp_path)
    profile = tmp_path / "profile.yaml"
    profile.write_text("name: T\nlevel: Junior\nlanguages:\n  - Python\n", encoding="utf-8")
    _insert_job(db, "low", discovered_at="2026-06-02T10:00:00+00:00")
    _insert_job(db, "high", discovered_at="2026-06-02T10:05:00+00:00")
    client = FakeJobAnalystClient(scores=[60, 90])  # low first (ASC discovered_at)

    with patch.object(job_analyst.httpx, "post", return_value=FakeHttpResp()):
        stats = job_analyst.run_analyst_pass(db, str(profile), "https://webhook", client)

    assert stats["scored"] == 2
    assert stats["notified"] == 1
    rows = _rows(db)
    assert rows["low"]["llm_score"] == 60 and rows["low"]["status"] == "scored"
    assert rows["high"]["llm_score"] == 90 and rows["high"]["status"] == "notified"
