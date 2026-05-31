from abc import ABC, abstractmethod
from typing import Optional

VALID_AGENT_STATES = {"idle", "running", "error", "dormant", "empty"}


class Agent(ABC):
    """Base class every agent must inherit from."""

    # Required class attributes (subclass must define)
    id: str           # short slug, e.g., "deal_hunter"
    name: str         # display name, e.g., "Deal Hunter"
    description: str  # one-line description
    version: str = "1.0"

    @abstractmethod
    def status(self) -> dict:
        """Return current agent status.

        Returns dict with at minimum:
            state: one of VALID_AGENT_STATES
            message: str — short human-readable status
            last_run: ISO timestamp or None

        Optional fields:
            output_count: int — number of outputs since start
            error: str — error message if state is "error"
        """
        pass

    @abstractmethod
    def recent_activity(self, limit: int = 10) -> list:
        """Return recent activity items for the dashboard feed.

        Each item: { timestamp, kind, message }
        kind in {"info", "success", "warn", "error"}
        """
        pass

    @abstractmethod
    def trigger(self, params: Optional[dict] = None) -> dict:
        """Manually trigger the agent. Synchronous.

        Returns dict: { triggered: bool, message: str }
        """
        pass

    def get_config(self) -> dict:
        """Return current configuration (optional override)."""
        return {}
