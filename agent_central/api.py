import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from agent_central.registry import registry

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

app = FastAPI(title="Agent Central")


@app.get("/health")
def health():
    return {"status": "ok", "agent_count": registry.count()}


@app.get("/api/agents")
def list_agents():
    """Return list of all registered agents with their status."""
    result = []
    for agent_id, agent in registry.all().items():
        try:
            status = agent.status()
        except Exception as e:
            status = {"state": "error", "message": str(e), "last_run": None}
        result.append({
            "id": agent.id,
            "name": agent.name,
            "description": agent.description,
            "version": agent.version,
            "status": status,
        })
    return {"agents": result, "count": len(result)}


@app.get("/api/agents/{agent_id}/status")
def agent_status(agent_id: str):
    agent = registry.get(agent_id)
    if not agent:
        return {"error": "agent not found", "agent_id": agent_id}, 404
    return agent.status()


@app.get("/api/agents/{agent_id}/recent")
def agent_recent(agent_id: str, limit: int = 10):
    agent = registry.get(agent_id)
    if not agent:
        return {"error": "agent not found", "agent_id": agent_id}, 404
    return {"items": agent.recent_activity(limit=limit)}


@app.post("/api/agents/{agent_id}/trigger")
def agent_trigger(agent_id: str):
    agent = registry.get(agent_id)
    if not agent:
        return {"error": "agent not found", "agent_id": agent_id}, 404
    return agent.trigger()


# Serve the command center UI
@app.get("/")
def root():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
