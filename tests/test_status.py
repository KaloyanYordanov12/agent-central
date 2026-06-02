"""Status / IPC tests.

Agent Central does NOT use file-based IPC — it polls Deal Hunter's HTTP
/status endpoint via StatusPoller and rebroadcasts changes over WebSocket.
These tests cover that real machinery: the agent-state contract, the poller's
initial state, the broadcast helper, and the frontend STATE_TO_ZONE contract.
"""
import asyncio
import json
import os
import re

from agent_central import VALID_AGENT_STATES
from agent_central import api
from agent_central.poller import StatusPoller


def test_valid_agent_states_contract():
    """Lock the documented agent-state vocabulary so changes are deliberate."""
    assert VALID_AGENT_STATES == {"idle", "running", "error", "dormant", "empty"}


def test_status_poller_initial_state():
    """A freshly constructed poller starts clean (not offline, no failures)."""
    poller = StatusPoller(broadcast_fn=lambda msg: None)
    assert poller.last_state is None
    assert poller.failure_count == 0
    assert poller.offline is False


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(text)


class _DeadWS:
    async def send_text(self, text):
        raise RuntimeError("connection dropped")


def test_broadcast_sends_json_to_clients():
    """broadcast() serializes the message and sends it to each connected client."""
    ws = _FakeWS()
    api._ws_clients.add(ws)
    try:
        asyncio.run(api.broadcast({"type": "status", "payload": {"state": "idle"}}))
        assert len(ws.sent) == 1
        msg = json.loads(ws.sent[0])
        assert msg["type"] == "status"
        assert msg["payload"]["state"] == "idle"
    finally:
        api._ws_clients.discard(ws)


def test_broadcast_drops_dead_clients():
    """A client whose send fails is removed from the active set."""
    dead = _DeadWS()
    api._ws_clients.add(dead)
    try:
        asyncio.run(api.broadcast({"type": "status", "payload": {}}))
        assert dead not in api._ws_clients
    finally:
        api._ws_clients.discard(dead)


def test_broadcast_no_clients_is_noop():
    """broadcast() with no connected clients must not raise."""
    asyncio.run(api.broadcast({"type": "status", "payload": {}}))


def test_frontend_state_to_zone_covers_pipeline_states():
    """The frontend STATE_TO_ZONE map must route every Deal Hunter pipeline
    state to a zone, or the character won't move on that state. This is a
    static-text contract check (not browser automation)."""
    index = os.path.join(os.path.dirname(api.__file__), "static", "index.html")
    with open(index, encoding="utf-8") as f:
        html = f.read()
    match = re.search(r"STATE_TO_ZONE\s*=\s*\{(.*?)\}", html, re.S)
    assert match, "STATE_TO_ZONE object not found in index.html"
    block = match.group(1)
    for state in (
        "scanning", "qualifying", "author_research",
        "writing", "critic", "posting", "idle", "offline",
    ):
        assert re.search(rf"\b{state}\b\s*:", block), (
            f"state '{state}' missing from STATE_TO_ZONE"
        )
