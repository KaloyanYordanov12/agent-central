"""Phase 1 tests: Secretary groundedness eval (objective, DB-computed truth).

Hermetic and $0: a real temp activity_log SQLite DB provides the ground truth,
and the Secretary is mocked (a fake ask_fn / canned result dicts). No Anthropic
calls, no embedding model. The point under test is that the truth comes from the
database and the grader honestly classifies right / wrong / hallucinated answers.
"""
from datetime import datetime, timezone

import pytest

from agent_central import activity_log
from agent_central.eval import grader, questions, runner
from agent_central.eval.questions import GroundednessQuestion


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def _seed_db(tmp_path):
    """A known activity_log: 3 agents active, 1 error, known recent states."""
    db = str(tmp_path / "activity.db")
    activity_log.init_db(db)
    activity_log.log_event("job_scout", "lifecycle", state="idle",
                           metadata={"event": "first_seen"})
    activity_log.log_event("job_scout", "state_change", state="scanning")
    activity_log.log_event("job_scout", "state_change", state="idle")
    activity_log.log_event("deal_hunter", "error", state="error")
    activity_log.log_event("job_analyst", "state_change", state="scanning")
    activity_log.log_event("job_analyst", "state_change", state="idle")  # last event
    return db


def _real_source(agent_id):
    """A source whose window spans all of today (so it contains real events)."""
    d = _today()
    return {
        "chunk_id": f"{agent_id}|{d}T00:00:00+00:00",
        "agent_id": agent_id,
        "window_start": f"{d}T00:00:00+00:00",
        "window_end": "2099-01-01T00:00:00+00:00",
        "score": 0.9,
    }


_FAKE_SOURCE = {
    "chunk_id": "deal_hunter|2020-01-01T00:00:00+00:00",
    "agent_id": "deal_hunter",
    "window_start": "2020-01-01T00:00:00+00:00",
    "window_end": "2020-01-01T00:15:00+00:00",
    "score": 0.5,
}


# --- truth functions read the real DB ----------------------------------------

def test_truth_agents_active_today(tmp_path):
    db = _seed_db(tmp_path)
    truth = questions.truth_agents_active_today(db)
    flat = {syn for group in truth for syn in group}
    assert "job scout" in flat and "job_analyst" in flat and "deal hunter" in flat
    assert len(truth) == 3


def test_truth_errors_today(tmp_path):
    db = _seed_db(tmp_path)
    assert questions.truth_errors_today(db) == 1


def test_truth_recent_states(tmp_path):
    db = _seed_db(tmp_path)
    assert questions.truth_job_scout_recent_state(db) == [["idle"]]
    assert questions.truth_job_analyst_recent_state(db) == [["idle"]]


def test_truth_most_recent_event_agent(tmp_path):
    db = _seed_db(tmp_path)
    assert questions.truth_most_recent_event_agent(db) == [["job analyst", "job_analyst"]]


def test_truth_job_analyst_passes_today(tmp_path):
    db = _seed_db(tmp_path)
    assert questions.truth_job_analyst_passes_today(db) == 1


def test_recent_state_empty_when_no_events(tmp_path):
    db = str(tmp_path / "empty.db")
    activity_log.init_db(db)
    assert questions.truth_job_scout_recent_state(db) == []


# --- matcher -----------------------------------------------------------------

def test_answer_matches_count_exact_token():
    assert grader.answer_matches_truth("count", 1, "There was 1 error today.")
    assert not grader.answer_matches_truth("count", 1, "There were 15 errors.")  # 1 not standalone
    assert not grader.answer_matches_truth("count", 25, "score was 250")


def test_answer_matches_count_zero_accepts_negation():
    assert grader.answer_matches_truth("count", 0, "No errors were logged today.")
    assert grader.answer_matches_truth("count", 0, "The count is 0.")
    assert not grader.answer_matches_truth("count", 0, "There were 3 errors.")


def test_answer_matches_contains_all_groups():
    truth = [["job scout", "job_scout"], ["secretary"]]
    assert grader.answer_matches_truth("contains", truth, "The Job Scout and Secretary ran.")
    assert not grader.answer_matches_truth("contains", truth, "Only the Job Scout ran.")


def test_answer_matches_contains_empty_truth_wants_negation():
    assert grader.answer_matches_truth("contains", [], "No agents were active.")
    assert not grader.answer_matches_truth("contains", [], "The Job Scout was active.")


# --- source verification (hallucination detector) ----------------------------

def test_verify_source_real_vs_fake(tmp_path):
    db = _seed_db(tmp_path)
    assert grader.verify_source(db, _real_source("deal_hunter")) is True
    assert grader.verify_source(db, _FAKE_SOURCE) is False           # window has no events
    assert grader.verify_source(db, {"agent_id": None}) is False     # no agent at all
    assert grader.verify_source(db, _real_source("ghost_agent")) is False  # agent never logged


# --- grade_groundedness end to end -------------------------------------------

def _errors_q():
    return GroundednessQuestion(
        id="errors_today", text="How many errors today?", kind="count",
        truth_fn=questions.truth_errors_today,
    )


def test_grade_correct(tmp_path):
    db = _seed_db(tmp_path)
    q = _errors_q()
    res = grader.grade_groundedness(
        q, 1, {"answer": "There was 1 error today.",
                "sources": [_real_source("deal_hunter")]}, db)
    assert res["outcome"] == "correct" and res["passed"] is True
    assert res["provenance"] == "computed from activity_log"


def test_grade_wrong(tmp_path):
    db = _seed_db(tmp_path)
    res = grader.grade_groundedness(
        _errors_q(), 1, {"answer": "There were 5 errors today.",
                          "sources": [_real_source("deal_hunter")]}, db)
    assert res["outcome"] == "wrong" and res["passed"] is False


def test_grade_hallucinated(tmp_path):
    db = _seed_db(tmp_path)
    # Right number, but cites a window that has no events -> fabricated grounding.
    res = grader.grade_groundedness(
        _errors_q(), 1, {"answer": "There was 1 error today.",
                         "sources": [_FAKE_SOURCE]}, db)
    assert res["outcome"] == "hallucinated" and res["passed"] is False
    assert res["hallucinated_sources"] == [_FAKE_SOURCE["chunk_id"]]


def test_grade_abstained(tmp_path):
    db = _seed_db(tmp_path)
    res = grader.grade_groundedness(
        _errors_q(), 1,
        {"answer": "Based on the activity log, I don't have information about that.",
         "sources": [_real_source("deal_hunter")]}, db)
    assert res["outcome"] == "abstained" and res["passed"] is False


# --- runner under SpendGuard -------------------------------------------------

def test_run_secretary_groundedness_mocked_no_spend(tmp_path):
    db = _seed_db(tmp_path)
    calls = []

    def ask_fn(text):
        calls.append(text)
        # A canned answer that happens to satisfy several questions, with a real
        # source so nothing reads as hallucinated.
        return {
            "answer": "Active today: Job Scout, Job Analyst, Deal Hunter. There was "
                      "1 error. Job Scout is idle. Job Analyst is idle. The Job "
                      "Analyst started 1 pass. The most recent event was Job Analyst.",
            "sources": [_real_source("job_analyst")],
            "model": "mock-haiku", "input_tokens": 100, "output_tokens": 20,
        }

    guard = runner.make_guard()
    out = runner.run_secretary_groundedness(db, ask_fn, guard=guard)
    assert len(calls) == len(questions.GROUNDEDNESS_QUESTIONS)
    assert out["summary"]["total"] == len(questions.GROUNDEDNESS_QUESTIONS)
    assert out["summary"]["passed"] >= 1          # at least some pass on a good answer
    assert out["capped"] is None
    assert all(r["provenance"] == "computed from activity_log" for r in out["results"])
    # Guard recorded a call + nonzero estimated cost per ask (no real money: mocked).
    assert guard.calls == len(calls)
    assert guard.cost > 0


def test_run_groundedness_zero_call_guard_spends_nothing(tmp_path):
    """The critical safety check: a 0-call guard makes the runner ask nothing."""
    db = _seed_db(tmp_path)
    calls = []

    def ask_fn(text):
        calls.append(text)
        return {"answer": "x", "sources": [], "input_tokens": 1, "output_tokens": 1}

    from agent_central.job_analyst import SpendGuard
    guard = SpendGuard(max_calls=0, max_cost_usd=1.0, max_seconds=900)
    out = runner.run_secretary_groundedness(db, ask_fn, guard=guard)
    assert calls == []                       # zero asks
    assert out["results"] == []
    assert out["capped"] == "max_calls"
