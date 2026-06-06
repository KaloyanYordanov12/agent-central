"""Phase 3 tests: scorecard assembly + persistence + the eval endpoints.

Hermetic and $0: the spending part (_build_eval_scorecard) is patched with a
canned scorecard, the scorecard path is redirected to a tmp file, and the
activity DB is a tmp file. No Anthropic calls.
"""
import json

import pytest

from agent_central import api, activity_log
from agent_central.eval import scorecard
from agent_central.job_analyst import SpendGuard


# --- scorecard assembly + persistence ----------------------------------------

def _fake_sections():
    ground = {
        "agent": "secretary", "check": "groundedness",
        "provenance": "computed from activity_log",
        "results": [
            {"id": "q1", "passed": True, "outcome": "correct",
             "provenance": "computed from activity_log"},
            {"id": "q2", "passed": False, "outcome": "wrong",
             "provenance": "computed from activity_log"},
        ],
        "summary": {"total": 2, "passed": 1}, "capped": None,
    }
    analyst = {
        "agent": "job_analyst", "check": "categorical",
        "provenance": "model-drafted (Opus 4.8), clear-cut",
        "results": [
            {"id": "c1", "title": "T1", "passed": True,
             "provenance": "model-drafted (Opus 4.8), clear-cut", "needs_review": False},
            {"id": "se2", "title": "Software Engineer II", "passed": False,
             "expected": "low", "provenance": "model-drafted (Opus 4.8), clear-cut",
             "needs_review": True},
        ],
        "summary": {"total": 2, "passed": 1}, "capped": None,
    }
    return [ground, analyst]


def test_build_scorecard_aggregates_and_flags():
    guard = SpendGuard()
    guard.calls = 4
    guard.cost = 0.012345
    card = scorecard.build_scorecard(_fake_sections(), guard=guard,
                                     generated_at="2026-06-06T00:00:00+00:00")
    assert card["overall"]["total"] == 4
    assert card["overall"]["passed"] == 2
    assert card["spend"]["calls"] == 4
    assert card["spend"]["estimated_cost_usd"] == 0.012345
    assert card["caps"]["max_cost_usd"] == 0.50
    # Failing cases are flattened with section context + provenance.
    failing_ids = {f["id"] for f in card["failing"]}
    assert failing_ids == {"q2", "se2"}
    assert all("provenance" in f for f in card["failing"])
    # needs_review surfaced for the analyst case only.
    assert [n["id"] for n in card["needs_review"]] == ["se2"]


def test_save_and_load_scorecard_roundtrip(tmp_path):
    path = str(tmp_path / "eval_scorecard.json")
    assert scorecard.load_scorecard(path) is None  # never run
    card = scorecard.build_scorecard(_fake_sections(),
                                     generated_at="2026-06-06T00:00:00+00:00")
    scorecard.save_scorecard(card, path)
    loaded = scorecard.load_scorecard(path)
    assert loaded["generated_at"] == "2026-06-06T00:00:00+00:00"
    assert loaded["overall"]["total"] == 4


# --- endpoints ---------------------------------------------------------------

def test_scorecard_endpoint_never_run(client, tmp_path, monkeypatch):
    monkeypatch.setattr(api, "EVAL_SCORECARD_PATH", str(tmp_path / "none.json"))
    resp = client.get("/api/eval/scorecard")
    assert resp.status_code == 200
    assert resp.json()["status"] == "never_run"


def test_run_endpoint_persists_and_returns(client, tmp_path, temp_activity_db, monkeypatch):
    path = str(tmp_path / "eval_scorecard.json")
    monkeypatch.setattr(api, "EVAL_SCORECARD_PATH", path)
    canned = scorecard.build_scorecard(_fake_sections(),
                                       generated_at="2026-06-06T12:00:00+00:00")
    monkeypatch.setattr(api, "_build_eval_scorecard", lambda: canned)

    resp = client.post("/api/eval/run")
    assert resp.status_code == 200
    body = resp.json()
    assert body["generated_at"] == "2026-06-06T12:00:00+00:00"
    assert body["overall"]["total"] == 4

    # The endpoint stamps a change-signature so the auto-run can skip-if-unchanged.
    assert "signature" in body
    assert set(body["signature"].keys()) == {"commit", "profile_hash"}

    # Persisted: the GET now returns the same scorecard.
    got = client.get("/api/eval/scorecard")
    assert got.status_code == 200
    assert got.json()["generated_at"] == "2026-06-06T12:00:00+00:00"

    # The Evaluator logged its run in the activity log (office honesty).
    events = activity_log.query_events(agent_id="evaluator")
    states = {e["state"] for e in events}
    assert "running-evals" in states and "idle" in states


def test_run_endpoint_rejects_concurrent(client, monkeypatch):
    monkeypatch.setattr(api, "_eval_running", True)
    resp = client.post("/api/eval/run")
    assert resp.status_code == 409


def test_run_endpoint_503_without_api_key(client, temp_activity_db, monkeypatch):
    # No key + reset cached Secretary deps so the key check actually runs.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(api, "_secretary_client", None, raising=False)
    monkeypatch.setattr(api, "_secretary_embedding_service", None, raising=False)
    monkeypatch.setattr(api, "_secretary_vector_index", None, raising=False)
    monkeypatch.setattr(api, "_eval_running", False)
    resp = client.post("/api/eval/run")
    assert resp.status_code == 503
