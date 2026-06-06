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

    # Stationary agents whose live state is derived from activity_log rather
    # than a dashboard endpoint. Deal Hunter is added separately from /status.
    DERIVED_AGENTS = ("job_scout", "job_analyst", "secretary", "evaluator")

    async def _broadcast_agent_states(self, deal_hunter_status: dict):
        """Emit a unified 'agent_states' message alongside the legacy 'status'.

        Deal Hunter's slice comes from its just-polled /status payload; the
        stationary agents' slices come from their most recent state_change/error
        event in activity_log. A DB error here must never break polling, so the
        derivation is guarded and falls back to idle.
        """
        agents = {
            "deal_hunter": {
                "state": deal_hunter_status.get("state"),
                "current_action": deal_hunter_status.get("current_action"),
            },
        }
        for agent_id in self.DERIVED_AGENTS:
            try:
                state = activity_log.get_current_state(agent_id)
            except Exception:
                logger.exception(f"get_current_state({agent_id}) failed")
                state = None
            agents[agent_id] = state or {"state": "idle"}

        await self.broadcast({"type": "agent_states", "agents": agents})

    async def _loop(self):
        async with httpx.AsyncClient(timeout=2.0) as client:
            while True:
                # Deal Hunter slice for this cycle's agent_states broadcast.
                # Defaults to last-known state so a transient poll failure
                # (before the offline threshold) doesn't blank Deal Hunter.
                dh_status = {
                    "agent_id": "deal_hunter",
                    "state": self.last_state or "idle",
                    "current_action": None,
                }
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
                    dh_status = status

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
                        # Legacy 'status' offline notice is sent once, at the
                        # transition, to preserve existing Deal Hunter behavior.
                        await self.broadcast({
                            "type": "status",
                            "payload": {
                                "agent_id": "deal_hunter",
                                "state": "offline",
                                "current_action": "Deal Hunter unreachable",
                                "last_changed_at": time.time(),
                            },
                        })
                    if self.offline:
                        dh_status = {
                            "agent_id": "deal_hunter",
                            "state": "offline",
                            "current_action": "Deal Hunter unreachable",
                        }

                # Multi-agent broadcast runs EVERY cycle regardless of Deal
                # Hunter's reachability — Job Scout / Job Analyst are independent
                # agents whose walking must keep updating even when Deal Hunter
                # is down. The legacy 'status' message above is preserved for
                # backward compat; this additive message carries all agent state.
                await self._broadcast_agent_states(dh_status)

                await asyncio.sleep(POLL_INTERVAL)
