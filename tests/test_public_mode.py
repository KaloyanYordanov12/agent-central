"""Phase 1 tests: the read-only public mode.

All hermetic and $0. They patch api.PUBLIC_MODE directly (the flag is read from
the AGENT_CENTRAL_PUBLIC env var at import time) and assert that public mode:
- disables the spend endpoints (POST /api/eval/run -> 403; the Secretary ask
  vector+LLM branch never runs),
- reports the flag via GET /api/config,
- starts NO spending or data-mutating background task (only the StatusPoller),
and that flag-off behavior is unchanged. No Anthropic calls.
"""
import asyncio

import pytest

from agent_central import api, activity_log


# --- GET /api/config ---------------------------------------------------------

def test_config_reports_public_mode_off_by_default(client, monkeypatch):
    monkeypatch.setattr(api, "PUBLIC_MODE", False)
    resp = client.get("/api/config")
    assert resp.status_code == 200
    assert resp.json() == {"public_mode": False}


def test_config_reports_public_mode_on(client, monkeypatch):
    monkeypatch.setattr(api, "PUBLIC_MODE", True)
    resp = client.get("/api/config")
    assert resp.status_code == 200
    assert resp.json() == {"public_mode": True}


# --- POST /api/eval/run is disabled in public mode ---------------------------

def test_eval_run_403_in_public_mode_without_spending(client, monkeypatch):
    monkeypatch.setattr(api, "PUBLIC_MODE", True)

    # If the (spending) builder is reached, fail loudly: it must never be called.
    def _must_not_run():
        raise AssertionError("_build_eval_scorecard must not run in public mode")
    monkeypatch.setattr(api, "_build_eval_scorecard", _must_not_run)

    resp = client.post("/api/eval/run")
    assert resp.status_code == 403
    assert "public demo" in resp.json()["detail"].lower()


def test_eval_run_works_when_flag_off(client, tmp_path, temp_activity_db, monkeypatch):
    # Flag off: the endpoint behaves exactly as before (canned builder, $0).
    monkeypatch.setattr(api, "PUBLIC_MODE", False)
    from agent_central.eval import scorecard
    path = str(tmp_path / "eval_scorecard.json")
    monkeypatch.setattr(api, "EVAL_SCORECARD_PATH", path)
    canned = scorecard.build_scorecard(
        [], guard=None, generated_at="2026-06-08T00:00:00+00:00")
    monkeypatch.setattr(api, "_build_eval_scorecard", lambda: canned)
    monkeypatch.setattr(api, "_eval_running", False)

    resp = client.post("/api/eval/run")
    assert resp.status_code == 200
    assert resp.json()["generated_at"] == "2026-06-08T00:00:00+00:00"


# --- POST /api/secretary/ask uses the structured path only in public mode ----

def _fail_if_called(*_a, **_k):
    raise AssertionError("the LLM/vector deps must not be built in public mode")


def test_ask_structured_path_in_public_mode(client, temp_activity_db, monkeypatch):
    monkeypatch.setattr(api, "PUBLIC_MODE", True)
    # The vector+LLM dependency builder must never be constructed.
    monkeypatch.setattr(api, "_get_secretary_deps", _fail_if_called)

    # Seed a recorded event so the structured count path returns a real answer.
    activity_log.log_event("job_scout", "state_change", state="scanning")

    resp = client.post("/api/secretary/ask",
                       json={"question": "How many activity events have been logged?"})
    assert resp.status_code == 200
    body = resp.json()
    # Answered from the deterministic DB path, with $0 spend (no model).
    assert body["path"] == "structured"
    assert body["model"] is None
    assert body["input_tokens"] == 0 and body["output_tokens"] == 0


def test_ask_semantic_question_friendly_in_public_mode(client, temp_activity_db, monkeypatch):
    monkeypatch.setattr(api, "PUBLIC_MODE", True)
    monkeypatch.setattr(api, "_get_secretary_deps", _fail_if_called)

    # A semantic question the structured path declines (returns None): public mode
    # must answer with a friendly $0 message, never falling through to the LLM.
    resp = client.post("/api/secretary/ask",
                       json={"question": "Why did Deal Hunter pick that particular deal?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == "public-demo"
    assert body["model"] is None
    assert "History tab" in body["answer"]


def test_ask_uses_llm_deps_when_flag_off(client, temp_activity_db, monkeypatch):
    # Flag off + a semantic question: the endpoint still reaches the deps builder
    # (here it raises RuntimeError -> 503, proving the vector/LLM branch is live).
    monkeypatch.setattr(api, "PUBLIC_MODE", False)

    def _raise_no_key():
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    monkeypatch.setattr(api, "_get_secretary_deps", _raise_no_key)

    resp = client.post("/api/secretary/ask",
                       json={"question": "Why did Deal Hunter pick that particular deal?"})
    assert resp.status_code == 503


# --- lifespan starts no spending / mutating task in public mode --------------

class _FakeTask:
    """Records start()/stop() without doing any real work."""
    def __init__(self, *args, **kwargs):
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True


def _patch_all_tasks(monkeypatch):
    """Replace every background-task class + DB writes with hermetic fakes."""
    created = {}

    def _maker(name):
        def factory(*args, **kwargs):
            inst = _FakeTask()
            created[name] = inst
            return inst
        return factory

    monkeypatch.setattr(api, "StatusPoller", _maker("poller"))
    monkeypatch.setattr(api, "IndexerTask", _maker("indexer"))
    monkeypatch.setattr(api, "JobScoutTask", _maker("scout"))
    monkeypatch.setattr(api, "JobAnalystTask", _maker("analyst"))
    monkeypatch.setattr(api, "EvaluatorTask", _maker("evaluator"))
    # Keep the DB pristine: no real init_db / log_event side effects in the test.
    monkeypatch.setattr(api.activity_log, "init_db", lambda *a, **k: None)
    monkeypatch.setattr(api.activity_log, "log_event", lambda *a, **k: 0)
    # Reset the module-level task handles the lifespan assigns.
    for g in ("_poller", "_indexer", "_job_scout", "_job_analyst", "_evaluator"):
        monkeypatch.setattr(api, g, None, raising=False)
    return created


def test_public_mode_starts_only_poller(monkeypatch):
    monkeypatch.setattr(api, "PUBLIC_MODE", True)
    created = _patch_all_tasks(monkeypatch)

    async def run():
        async with api.lifespan(api.app):
            pass
    asyncio.run(run())

    # The read-only poller is the ONLY task that ran.
    assert created["poller"].started is True
    assert "indexer" not in created
    assert "scout" not in created
    assert "analyst" not in created
    assert "evaluator" not in created


def test_normal_mode_starts_all_tasks(monkeypatch):
    monkeypatch.setattr(api, "PUBLIC_MODE", False)
    created = _patch_all_tasks(monkeypatch)

    async def run():
        async with api.lifespan(api.app):
            pass
    asyncio.run(run())

    # Flag off: every background task starts as before.
    for name in ("poller", "indexer", "scout", "analyst", "evaluator"):
        assert created[name].started is True, f"{name} did not start"
