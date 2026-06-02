"""WebSocket connection tests for /ws/status.

The server does NOT push an initial payload on connect — it only broadcasts
when the StatusPoller detects a Deal Hunter state change. So these tests only
assert that connections are accepted and the connect/disconnect lifecycle is
clean; calling receive_*() here would block forever.
"""


def test_websocket_accepts_connection(client):
    """/ws/status accepts an incoming connection."""
    with client.websocket_connect("/ws/status") as websocket:
        assert websocket is not None


def test_websocket_connect_disconnect_cycle(client):
    """Connecting then disconnecting twice works (server cleans up clients)."""
    with client.websocket_connect("/ws/status"):
        pass
    with client.websocket_connect("/ws/status"):
        pass
