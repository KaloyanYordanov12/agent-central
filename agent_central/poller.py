"""
Background poller — fetches Deal Hunter's state from its /status endpoint
and broadcasts state changes to connected WebSocket clients.

Polled URL is hardcoded to Deal Hunter on localhost:8000. If Deal Hunter
goes unreachable for 3 consecutive polls, an 'offline' status is broadcast.
"""
import asyncio
import logging
import time
from typing import Optional

import httpx

from agent_central import activity_log

logger = logging.getLogger(__name__)

DEAL_HUNTER_URL = "http://127.0.0.1:8000/status"
POLL_INTERVAL = 1.5  # seconds
OFFLINE_THRESHOLD = 3  # consecutive failures before declaring offline


class StatusPoller:
    """Polls Deal Hunter's /status endpoint and pushes results to a broadcast function."""

    def __init__(self, broadcast_fn):
        self.broadcast = broadcast_fn
        self.last_state: Optional[str] = None
        self.failure_count = 0
        self.offline = False
        self._task: Optional[asyncio.Task] = None

    @staticmethod
    def _log_safe(agent_id, event_type, **kwargs):
        """Log an activity event without ever letting a logging failure break polling."""
        try:
            activity_log.log_event(agent_id, event_type, **kwargs)
        except Exception:
            logger.exception(f"activity log ({event_type}) failed")

    async def start(self):
        self._task = asyncio.create_task(self._loop())
        logger.info("StatusPoller started")

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("StatusPoller stopped")

    async def _loop(self):
        async with httpx.AsyncClient(timeout=2.0) as client:
            while True:
                try:
                    response = await client.get(DEAL_HUNTER_URL)
                    response.raise_for_status()
                    status = response.json()
                    agent_id = status.get("agent_id", "deal_hunter")

                    if self.offline:
                        logger.info("Deal Hunter back online")
                        self._log_safe(
                            agent_id, "lifecycle", state="online",
                            metadata={"transition": "back_online"},
                        )
                        self.offline = False
                    self.failure_count = 0

                    current_state = status.get("state")
                    if current_state != self.last_state:
                        logger.info(f"State change: {self.last_state} -> {current_state}")
                        # Activity-log site for state changes (and first appearance).
                        try:
                            if self.last_state is None:
                                activity_log.log_event(
                                    agent_id, "lifecycle", state=current_state,
                                    metadata={"event": "first_seen"},
                                )
                            activity_log.record_state_change(
                                agent_id, current_state, prev_state=self.last_state,
                                payload={"current_action": status.get("current_action")},
                            )
                        except Exception:
                            logger.exception("activity log (state_change) failed")
                        self.last_state = current_state

                    await self.broadcast({
                        "type": "status",
                        "payload": status,
                    })

                except (httpx.RequestError, httpx.HTTPStatusError) as e:
                    self.failure_count += 1
                    if self.failure_count >= OFFLINE_THRESHOLD and not self.offline:
                        logger.warning(
                            f"Deal Hunter unreachable after {self.failure_count} attempts: {e}"
                        )
                        self.offline = True
                        self._log_safe(
                            "deal_hunter", "lifecycle", state="offline",
                            metadata={"reason": "unreachable", "failures": self.failure_count},
                        )
                        await self.broadcast({
                            "type": "status",
                            "payload": {
                                "agent_id": "deal_hunter",
                                "state": "offline",
                                "current_action": "Deal Hunter unreachable",
                                "last_changed_at": time.time(),
                            },
                        })

                await asyncio.sleep(POLL_INTERVAL)
