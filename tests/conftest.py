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


@pytest.fixture
def temp_activity_db(tmp_path):
    """Point the activity_log module at a fresh temp SQLite DB with schema created.

    The `client` fixture bypasses the app lifespan (where init_db normally runs),
    so any test exercising the activity log must initialise the DB itself via this
    fixture. The module-level DB path is restored on teardown so tests don't leak
    into each other or create the real data/activity.db.
    """
    from agent_central import activity_log

    old_path = activity_log._DB_PATH
    db_path = str(tmp_path / "activity.db")
    activity_log.init_db(db_path)
    yield db_path
    activity_log._DB_PATH = old_path
