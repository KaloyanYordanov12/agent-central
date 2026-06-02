import pytest
from fastapi.testclient import TestClient

from agent_central.api import app


@pytest.fixture
def client():
    """Synchronous test client for HTTP + WebSocket endpoints.

    Intentionally NOT used as a context manager, so the app lifespan does not
    run. That means the background StatusPoller (which would make real network
    calls to Deal Hunter on :8000) never starts, keeping tests hermetic and
    non-flaky. The routes under test do not depend on the poller.
    """
    return TestClient(app)
