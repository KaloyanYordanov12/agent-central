from typing import Dict, Optional

from agent_central.agent_base import Agent


class AgentRegistry:
    """Singleton registry for all active agents."""

    def __init__(self):
        self._agents: Dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        """Register an agent instance by its id."""
        if not isinstance(agent, Agent):
            raise TypeError(f"Expected Agent subclass, got {type(agent)}")
        self._agents[agent.id] = agent

    def get(self, agent_id: str) -> Optional[Agent]:
        return self._agents.get(agent_id)

    def all(self) -> Dict[str, Agent]:
        return dict(self._agents)

    def count(self) -> int:
        return len(self._agents)


# Module-level singleton
registry = AgentRegistry()
