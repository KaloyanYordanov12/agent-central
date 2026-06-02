"""Tests for the Ask Secretary RAG layer (agent_central/secretary.py) and the
POST /api/secretary/ask endpoint.

No real Anthropic API calls and no embedding-model load: a FakeEmbeddingService
provides fixed vectors, a FakeSecretaryClient stands in for the LLM, and a real
ChromaDB index runs on a tmp dir.
"""
import json

import pytest

from agent_central import api, indexer, secretary


@pytest.fixture
def temp_chroma_dir(tmp_path):
    return str(tmp_path / "chroma")


class FakeEmbeddingService:
    """Deterministic fixed-vector embedder — no model load."""

    def embed_texts(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


class FakeSecretaryClient:
    """Stands in for SecretaryClient.ask — never touches the network."""

    def __init__(self):
        self.calls = []

    def ask(self, question, context_chunks):
        self.calls.append((question, context_chunks))
        return {"answer": "MOCK ANSWER", "model": "mock-haiku",
                "input_tokens": 11, "output_tokens": 7}


# --- _build_messages (pure) --------------------------------------------------

def test_build_messages_includes_question_and_context(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    client = secretary.SecretaryClient()
    chunks = [{
        "chunk_id": "deal_hunter|w1",
        "summary": "deal_hunter scanned r/SaaS",
        "metadata": {"agent_id": "deal_hunter"},
        "distance": 0.1,
    }]
    messages = client._build_messages("what did it scan?", chunks)
    blob = json.dumps(messages)
    assert "what did it scan?" in blob
    assert "scanned r/SaaS" in blob
    assert "deal_hunter|w1" in blob


def test_build_messages_handles_no_chunks(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    client = secretary.SecretaryClient()
    messages = client._build_messages("anything happen?", [])
    blob = json.dumps(messages)
    assert "anything happen?" in blob
    assert "No activity log context" in blob


# --- SecretaryClient key handling --------------------------------------------

def test_secretary_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        secretary.SecretaryClient()


def test_secretary_client_reads_env_var(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-value")
    client = secretary.SecretaryClient()  # must not raise
    assert client.model  # has a model string


# --- ask_secretary orchestrator ----------------------------------------------

def test_ask_secretary_handles_empty_index(temp_chroma_dir):
    idx = indexer.VectorIndex(temp_chroma_dir)  # empty
    result = secretary.ask_secretary(
        "what happened?", idx, FakeEmbeddingService(), FakeSecretaryClient(),
    )
    assert result["sources"] == []
    assert result["model"] is None
    assert result["input_tokens"] == 0
    assert result["output_tokens"] == 0
    assert "don't have" in result["answer"].lower()


def test_ask_secretary_returns_sources_and_answer(temp_chroma_dir):
    idx = indexer.VectorIndex(temp_chroma_dir)
    chunk = indexer.Chunk(
        "deal_hunter|w", "deal_hunter", "2026-06-02T14:30:00+00:00",
        "2026-06-02T14:45:00+00:00", 2, "deal_hunter scanned and idled",
        [1, 2], ["scanning", "idle"],
    )
    idx.upsert_chunks([chunk], [[1.0, 0.0, 0.0]])

    fake_client = FakeSecretaryClient()
    result = secretary.ask_secretary(
        "what did deal hunter do?", idx, FakeEmbeddingService(), fake_client, top_k=5,
    )
    assert result["answer"] == "MOCK ANSWER"
    assert result["model"] == "mock-haiku"
    assert result["input_tokens"] == 11
    assert result["output_tokens"] == 7
    assert len(result["sources"]) == 1
    src = result["sources"][0]
    assert src["chunk_id"] == "deal_hunter|w"
    assert src["agent_id"] == "deal_hunter"
    assert src["window_start"] == "2026-06-02T14:30:00+00:00"
    assert isinstance(src["score"], float) and 0 < src["score"] <= 1
    assert len(fake_client.calls) == 1  # LLM consulted exactly once


# --- FastAPI endpoint --------------------------------------------------------

def test_ask_endpoint_validates_empty_question(client):
    resp = client.post("/api/secretary/ask", json={"question": "   "})
    assert resp.status_code == 400


def test_ask_endpoint_handles_missing_api_key(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Reset cached singletons so the key check actually runs for this request.
    monkeypatch.setattr(api, "_secretary_client", None, raising=False)
    monkeypatch.setattr(api, "_secretary_embedding_service", None, raising=False)
    monkeypatch.setattr(api, "_secretary_vector_index", None, raising=False)
    resp = client.post("/api/secretary/ask", json={"question": "what happened today?"})
    assert resp.status_code == 503
