"""Phase 2 tests: hybrid retrieval (structured count/recency/aggregation path).

Hermetic and $0: a real temp activity_log SQLite DB is the ground truth, the
structured path is pure DB queries (no LLM), and the vector path is exercised with
a fake embedder + fake Claude client. The structured answers are checked for
correctness AND that their cited sources verify against the DB (reusing the eval's
own verify_source), and a semantic question is confirmed to still use the vector
path so existing Q&A is not regressed.
"""
import pytest

from agent_central import activity_log, indexer, secretary, structured_qa
from agent_central.eval import grader


def _seed(tmp_path):
    db = str(tmp_path / "activity.db")
    activity_log.init_db(db)
    activity_log.log_event("job_scout", "state_change", state="scanning")
    activity_log.log_event("job_scout", "state_change", state="idle")
    activity_log.log_event("deal_hunter", "error", state="error")
    activity_log.log_event("job_analyst", "state_change", state="scanning")
    activity_log.log_event("job_analyst", "state_change", state="idle")  # last event
    return db


def _sources_verify(db, result):
    return all(grader.verify_source(db, s) for s in result["sources"])


class _FakeEmbedding:
    def embed_texts(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


class _FakeClient:
    def __init__(self):
        self.calls = []

    def ask(self, question, context_chunks):
        self.calls.append((question, context_chunks))
        return {"answer": "MOCK ANSWER", "model": "mock-haiku",
                "input_tokens": 5, "output_tokens": 3}


class _ExplodingClient:
    """Fails the test loudly if the LLM is ever consulted on the structured path."""
    def ask(self, question, context_chunks):
        raise AssertionError("structured path must NOT call the LLM")


# --- structured path: recency ------------------------------------------------

def test_recency_most_recent_state_for_agent(tmp_path):
    db = _seed(tmp_path)
    res = structured_qa.structured_answer(
        "What is the most recent state recorded for the Job Scout?", db)
    assert res is not None
    assert "idle" in res["answer"].lower()
    assert res["model"] is None  # no LLM
    assert res["sources"] and _sources_verify(db, res)


def test_recency_most_recent_event_agent(tmp_path):
    db = _seed(tmp_path)
    res = structured_qa.structured_answer(
        "Which agent logged the most recent activity event?", db)
    assert res is not None
    assert "job analyst" in res["answer"].lower()
    assert _sources_verify(db, res)


# --- structured path: count --------------------------------------------------

def test_count_errors_today(tmp_path):
    db = _seed(tmp_path)
    res = structured_qa.structured_answer(
        "How many errors were logged across all agents today?", db)
    assert res is not None
    assert "1 error" in res["answer"]
    assert _sources_verify(db, res)


def test_count_errors_zero_is_honest(tmp_path):
    db = str(tmp_path / "noerr.db")
    activity_log.init_db(db)
    activity_log.log_event("job_scout", "state_change", state="idle")  # no errors
    res = structured_qa.structured_answer("How many errors were logged today?", db)
    assert res is not None
    low = res["answer"].lower()
    assert "0 error" in low or "no error" in low
    assert res["sources"] == []  # nothing to cite, and nothing fabricated


def test_count_agent_passes_today(tmp_path):
    db = _seed(tmp_path)
    res = structured_qa.structured_answer(
        "How many times did the Job Analyst start a scoring pass today?", db)
    assert res is not None
    assert "1 scoring pass" in res["answer"]
    assert _sources_verify(db, res)


# --- structured path: aggregation --------------------------------------------

def test_active_agents_today_lists_all(tmp_path):
    db = _seed(tmp_path)
    res = structured_qa.structured_answer("Which agents have been active today?", db)
    assert res is not None
    low = res["answer"].lower()
    assert "job scout" in low and "job analyst" in low and "deal hunter" in low
    assert _sources_verify(db, res)


# --- honesty: no data --------------------------------------------------------

def test_recency_no_data_for_unseen_agent(tmp_path):
    db = _seed(tmp_path)
    res = structured_qa.structured_answer(
        "What is the most recent state recorded for the Secretary?", db)
    assert res is not None
    assert "no recorded state" in res["answer"].lower()
    assert res["sources"] == []  # honest: no fabricated source


# --- routing: semantic questions stay on the vector path ---------------------

def test_semantic_question_is_not_structured(tmp_path):
    db = _seed(tmp_path)
    # An open semantic question has no count/recency/aggregation intent.
    assert structured_qa.structured_answer(
        "What kind of work does Deal Hunter focus on?", db) is None


def test_ask_secretary_uses_structured_path_without_llm(tmp_path):
    db = _seed(tmp_path)
    res = secretary.ask_secretary(
        "What is the most recent state recorded for the Job Scout?",
        vector_index=None, embedding_service=None,
        secretary_client=_ExplodingClient(), db_path=db)
    assert res["path"] == "structured"
    assert "idle" in res["answer"].lower()


def test_ask_secretary_semantic_still_uses_vector_path(tmp_path):
    db = _seed(tmp_path)
    idx = indexer.VectorIndex(str(tmp_path / "chroma"))
    chunk = indexer.Chunk(
        "deal_hunter|w", "deal_hunter", "2026-06-05T14:30:00+00:00",
        "2026-06-05T14:45:00+00:00", 1, "deal_hunter scanned a subreddit", [1], ["scanning"])
    idx.upsert_chunks([chunk], [[1.0, 0.0, 0.0]])
    client = _FakeClient()
    res = secretary.ask_secretary(
        "Summarize what Deal Hunter focuses on.", vector_index=idx,
        embedding_service=_FakeEmbedding(), secretary_client=client, db_path=db)
    assert res["answer"] == "MOCK ANSWER"          # came from the vector + LLM path
    assert res.get("path") != "structured"
    assert len(client.calls) == 1                  # vector path consulted the LLM once
