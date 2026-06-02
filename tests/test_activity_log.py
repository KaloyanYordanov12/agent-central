"""Tests for the activity logging foundation (agent_central/activity_log.py)
and the GET /api/secretary/history endpoint.

Each test uses a real SQLite file in a tmp dir (via the temp_activity_db fixture)
— no mocking of the database.
"""
import os
import sqlite3

from agent_central import activity_log


def test_init_db_creates_schema(tmp_path):
    db_path = str(tmp_path / "activity.db")
    activity_log.init_db(db_path)
    assert os.path.exists(db_path)

    conn = sqlite3.connect(db_path)
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        indexes = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
    finally:
        conn.close()

    assert "activity_log" in tables
    assert {"idx_agent_id", "idx_timestamp", "idx_event_type"}.issubset(indexes)


def test_log_event_inserts_row(temp_activity_db):
    row_id = activity_log.log_event(
        "deal_hunter", "state_change", state="scanning",
        payload={"target_subreddit": "r/Entrepreneur"},
        metadata={"previous_state": "idle"},
    )
    assert isinstance(row_id, int) and row_id > 0

    events = activity_log.query_events()
    assert len(events) == 1
    e = events[0]
    assert e["agent_id"] == "deal_hunter"
    assert e["event_type"] == "state_change"
    assert e["state"] == "scanning"
    assert e["payload"] == {"target_subreddit": "r/Entrepreneur"}
    assert e["metadata"] == {"previous_state": "idle"}
    assert e["timestamp"]  # non-empty ISO timestamp


def test_log_event_handles_none_payload(temp_activity_db):
    activity_log.log_event("deal_hunter", "lifecycle")  # no state/payload/metadata
    e = activity_log.query_events()[0]
    assert e["state"] is None
    assert e["payload"] is None
    assert e["metadata"] is None


def test_query_events_filters_by_agent_id(temp_activity_db):
    activity_log.log_event("deal_hunter", "state_change", state="scanning")
    activity_log.log_event("other_agent", "state_change", state="idle")

    out = activity_log.query_events(agent_id="deal_hunter")
    assert len(out) == 1
    assert out[0]["agent_id"] == "deal_hunter"


def test_query_events_filters_by_event_type(temp_activity_db):
    activity_log.log_event("a", "state_change", state="x")
    activity_log.log_event("a", "lifecycle", state="online")
    activity_log.log_event("a", "error", metadata={"msg": "boom"})

    out = activity_log.query_events(event_type="lifecycle")
    assert len(out) == 1
    assert out[0]["event_type"] == "lifecycle"


def test_query_events_respects_limit_and_offset(temp_activity_db):
    for i in range(5):
        activity_log.log_event("a", "state_change", state=f"s{i}")

    page1 = activity_log.query_events(limit=2, offset=0)
    page2 = activity_log.query_events(limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    # pages don't overlap
    assert {e["id"] for e in page1}.isdisjoint({e["id"] for e in page2})


def test_query_events_orders_newest_first(temp_activity_db):
    first_id = activity_log.log_event("a", "state_change", state="first")
    last_id = activity_log.log_event("a", "state_change", state="last")

    out = activity_log.query_events()
    assert out[0]["id"] == last_id
    assert out[0]["state"] == "last"
    assert out[-1]["id"] == first_id


def test_query_events_caps_limit_at_1000(temp_activity_db):
    # An over-large limit must be capped, not error.
    out = activity_log.query_events(limit=999999)
    assert isinstance(out, list)


def test_get_event_count(temp_activity_db):
    activity_log.log_event("a", "state_change", state="x")
    activity_log.log_event("b", "state_change", state="y")
    assert activity_log.get_event_count() == 2
    assert activity_log.get_event_count(agent_id="a") == 1


def test_state_change_triggers_log_event(temp_activity_db):
    """record_state_change writes a state_change row when the state changes."""
    row_id = activity_log.record_state_change("deal_hunter", "scanning", prev_state="idle")
    assert isinstance(row_id, int) and row_id > 0

    events = activity_log.query_events(event_type="state_change")
    assert len(events) == 1
    assert events[0]["state"] == "scanning"
    assert events[0]["metadata"] == {"previous_state": "idle"}


def test_no_log_on_unchanged_state(temp_activity_db):
    """record_state_change is a no-op when the state is unchanged."""
    result = activity_log.record_state_change("deal_hunter", "idle", prev_state="idle")
    assert result is None
    assert activity_log.get_event_count() == 0


def test_history_endpoint_returns_events(client, temp_activity_db):
    activity_log.log_event(
        "deal_hunter", "state_change", state="scanning",
        metadata={"previous_state": "idle"},
    )
    resp = client.get("/api/secretary/history")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert isinstance(data["events"], list)
    assert data["events"][0]["agent_id"] == "deal_hunter"


def test_history_endpoint_filters_by_event_type(client, temp_activity_db):
    activity_log.log_event("deal_hunter", "state_change", state="scanning")
    activity_log.log_event("deal_hunter", "lifecycle", state="online")

    resp = client.get("/api/secretary/history", params={"event_type": "lifecycle"})
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert len(events) >= 1
    assert all(e["event_type"] == "lifecycle" for e in events)
