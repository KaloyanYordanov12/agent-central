"""Tests for the background activity indexer (agent_central/indexer.py).

Chunking/summarization tests are pure (no model, no DB). Embedding and vector-
index tests use the real sentence-transformers model / real ChromaDB on disk —
no mocking, per the spec. The embedding model loads once via a module-scoped
fixture (it's slow, ~3-5s).
"""
import pytest

from agent_central import activity_log, indexer


@pytest.fixture(scope="module")
def embedding_service():
    """One EmbeddingService for the module (model loads lazily on first embed)."""
    return indexer.EmbeddingService()


@pytest.fixture
def temp_chroma_dir(tmp_path):
    return str(tmp_path / "chroma")


def _ev(event_id, agent_id, ts, event_type="state_change", state=None,
        payload=None, metadata=None):
    return {
        "id": event_id, "timestamp": ts, "agent_id": agent_id,
        "event_type": event_type, "state": state,
        "payload": payload, "metadata": metadata,
    }


# --- chunking (pure) ---------------------------------------------------------

def test_chunk_events_groups_by_time_window():
    events = [
        _ev(1, "deal_hunter", "2026-06-02T14:30:00+00:00", state="idle"),
        _ev(2, "deal_hunter", "2026-06-02T14:32:00+00:00", state="scanning"),
        _ev(3, "deal_hunter", "2026-06-02T14:46:00+00:00", state="idle"),
        _ev(4, "deal_hunter", "2026-06-02T14:48:00+00:00", state="writing"),
    ]
    chunks = indexer.chunk_events(events, window_minutes=15)
    assert len(chunks) == 2
    assert chunks[0].window_start.startswith("2026-06-02T14:30")
    assert chunks[1].window_start.startswith("2026-06-02T14:45")
    assert chunks[0].event_count == 2
    assert chunks[1].event_count == 2


def test_chunk_events_groups_by_agent_id():
    events = [
        _ev(1, "deal_hunter", "2026-06-02T14:30:00+00:00", state="idle"),
        _ev(2, "other_agent", "2026-06-02T14:31:00+00:00", state="idle"),
    ]
    chunks = indexer.chunk_events(events, window_minutes=15)
    assert len(chunks) == 2
    assert {c.agent_id for c in chunks} == {"deal_hunter", "other_agent"}


def test_summarize_chunk_includes_state_transitions():
    events = [
        _ev(1, "a", "2026-06-02T14:30:00+00:00", "state_change", "idle",
            metadata={"previous_state": None}),
        _ev(2, "a", "2026-06-02T14:31:00+00:00", "state_change", "researching",
            metadata={"previous_state": "idle"}),
        _ev(3, "a", "2026-06-02T14:32:00+00:00", "state_change", "idle",
            metadata={"previous_state": "researching"}),
    ]
    summary = indexer.summarize_chunk(events)
    assert "idle -> researching -> idle" in summary


def test_summarize_chunk_handles_lifecycle_events():
    events = [
        _ev(1, "deal_hunter", "2026-06-02T14:30:00+00:00", "lifecycle", "offline",
            metadata={"reason": "unreachable"}),
    ]
    summary = indexer.summarize_chunk(events)
    assert "Lifecycle" in summary
    assert "offline" in summary


def test_summarize_chunk_handles_empty_payload():
    events = [
        _ev(1, "a", "2026-06-02T14:30:00+00:00", "state_change", "idle",
            payload=None, metadata=None),
        _ev(2, "a", "2026-06-02T14:31:00+00:00", "output", None, payload=None),
    ]
    summary = indexer.summarize_chunk(events)  # must not crash
    assert isinstance(summary, str) and summary


# --- embeddings (real model) -------------------------------------------------

def test_embedding_service_returns_correct_shape(embedding_service):
    vecs = embedding_service.embed_texts(["hello world", "second string", "third one"])
    assert len(vecs) == 3
    assert all(isinstance(v, list) for v in vecs)
    assert all(isinstance(x, float) for x in vecs[0])
    assert len({len(v) for v in vecs}) == 1  # all same dimension


# --- vector index (real ChromaDB, hand-crafted embeddings) -------------------

def test_vector_index_upsert_and_query(temp_chroma_dir):
    idx = indexer.VectorIndex(temp_chroma_dir)
    chunks = [
        indexer.Chunk("a|w1", "a", "2026-06-02T14:30:00+00:00",
                      "2026-06-02T14:45:00+00:00", 1, "alpha summary", [1], ["idle"]),
        indexer.Chunk("a|w2", "a", "2026-06-02T14:45:00+00:00",
                      "2026-06-02T15:00:00+00:00", 1, "beta summary", [2], ["scanning"]),
        indexer.Chunk("b|w1", "b", "2026-06-02T14:30:00+00:00",
                      "2026-06-02T14:45:00+00:00", 1, "gamma summary", [3], ["idle"]),
    ]
    embeddings = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    idx.upsert_chunks(chunks, embeddings)

    assert idx.count() == 3
    results = idx.query([1.0, 0.0, 0.0], n_results=3)
    assert results[0]["chunk_id"] == "a|w1"
    # list fields round-trip back from JSON metadata
    assert results[0]["metadata"]["event_ids"] == [1]
    assert results[0]["metadata"]["states_seen"] == ["idle"]


def test_vector_index_metadata_filter(temp_chroma_dir):
    idx = indexer.VectorIndex(temp_chroma_dir)
    chunks = [
        indexer.Chunk("dh|w", "deal_hunter", "2026-06-02T14:30:00+00:00",
                      "2026-06-02T14:45:00+00:00", 1, "dh summary", [1], ["idle"]),
        indexer.Chunk("ot|w", "other", "2026-06-02T14:30:00+00:00",
                      "2026-06-02T14:45:00+00:00", 1, "other summary", [2], ["idle"]),
    ]
    idx.upsert_chunks(chunks, [[1.0, 0.0], [0.0, 1.0]])

    results = idx.query([1.0, 0.0], n_results=5, where={"agent_id": "deal_hunter"})
    assert len(results) >= 1
    assert all(r["metadata"]["agent_id"] == "deal_hunter" for r in results)


# --- index state -------------------------------------------------------------

def test_index_state_persistence(tmp_path):
    path = str(tmp_path / "index_state.json")
    state = indexer.IndexState(
        path=path, last_indexed_event_id=42,
        last_run_at="2026-06-02T14:30:00+00:00", total_chunks=7,
    )
    state.save()
    loaded = indexer.IndexState.load(path)
    assert loaded.last_indexed_event_id == 42
    assert loaded.total_chunks == 7
    assert loaded.last_run_at == "2026-06-02T14:30:00+00:00"


# --- full pass (real model + real ChromaDB + real activity DB) ---------------

def test_run_index_pass_indexes_new_events(temp_activity_db, temp_chroma_dir,
                                           tmp_path, embedding_service):
    activity_log.log_event("deal_hunter", "state_change", state="scanning",
                           metadata={"previous_state": "idle"})
    activity_log.log_event("deal_hunter", "state_change", state="idle",
                           metadata={"previous_state": "scanning"})
    state = indexer.IndexState(path=str(tmp_path / "index_state.json"))

    stats = indexer.run_index_pass(temp_activity_db, temp_chroma_dir,
                                   embedding_service, state)
    assert stats["new_events"] == 2
    assert stats["new_chunks"] >= 1
    assert indexer.VectorIndex(temp_chroma_dir).count() >= 1
    assert state.last_indexed_event_id > 0


def test_run_index_pass_is_idempotent(temp_activity_db, temp_chroma_dir,
                                      tmp_path, embedding_service):
    activity_log.log_event("deal_hunter", "state_change", state="scanning")
    state = indexer.IndexState(path=str(tmp_path / "index_state.json"))

    indexer.run_index_pass(temp_activity_db, temp_chroma_dir, embedding_service, state)
    stats2 = indexer.run_index_pass(temp_activity_db, temp_chroma_dir,
                                    embedding_service, state)
    assert stats2["new_events"] == 0
    assert stats2["new_chunks"] == 0


def test_run_index_pass_only_indexes_new_events(temp_activity_db, temp_chroma_dir,
                                                tmp_path, embedding_service):
    activity_log.log_event("deal_hunter", "state_change", state="scanning")
    state = indexer.IndexState(path=str(tmp_path / "index_state.json"))

    stats1 = indexer.run_index_pass(temp_activity_db, temp_chroma_dir,
                                    embedding_service, state)
    assert stats1["new_events"] == 1

    activity_log.log_event("deal_hunter", "state_change", state="idle")
    activity_log.log_event("deal_hunter", "state_change", state="writing")

    stats2 = indexer.run_index_pass(temp_activity_db, temp_chroma_dir,
                                    embedding_service, state)
    assert stats2["new_events"] == 2  # only the two newly-logged events
