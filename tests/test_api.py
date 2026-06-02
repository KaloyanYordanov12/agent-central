"""HTTP endpoint tests for the Agent Central FastAPI app."""


def test_health_returns_200(client):
    """Health endpoint returns 200 with the expected shape."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "agent_count" in data


def test_health_returns_json(client):
    """Health endpoint advertises a JSON content-type."""
    response = client.get("/health")
    assert "application/json" in response.headers["content-type"]


def test_health_agent_count_is_int(client):
    """agent_count should be an integer (registry.count())."""
    data = client.get("/health").json()
    assert isinstance(data["agent_count"], int)


def test_list_agents_empty_registry(client):
    """No agents are registered at import time, so the registry is empty."""
    response = client.get("/api/agents")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 0
    assert data["agents"] == []


def test_nonexistent_endpoint_returns_404(client):
    """Unknown endpoints 404 cleanly."""
    response = client.get("/this-does-not-exist")
    assert response.status_code == 404


def test_root_serves_frontend(client):
    """The command-center HTML is served from /."""
    response = client.get("/")
    assert response.status_code == 200
    assert "AGENT CENTRAL" in response.text


def test_static_index_served(client):
    """The static mount serves index.html under /static."""
    response = client.get("/static/index.html")
    assert response.status_code == 200
    assert "AGENT CENTRAL" in response.text


def test_dashboard_includes_secretary_assets(client):
    """Step 4 regression: the dashboard ships the Secretary popup + its script."""
    html = client.get("/").text
    assert 'id="secretary-popup"' in html          # popup markup present
    assert "/static/secretary.js" in html           # references the new JS file


def test_secretary_js_is_served(client):
    """The Secretary JS module is served from the static mount."""
    response = client.get("/static/secretary.js")
    assert response.status_code == 200
    assert "openSecretaryPopup" in response.text
