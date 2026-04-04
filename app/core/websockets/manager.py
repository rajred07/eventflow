"""
WebSocket Connection Manager — tracks active planner dashboard connections.

Architecture:
    Each planner opens a WebSocket to /ws/events/{event_id}/dashboard.
    This manager maps event_id → set of active WebSocket connections.
    When a Redis Pub/Sub message arrives for event X, the manager
    pushes the payload to every connection subscribed to event X.

    Multiple planners can watch the same event simultaneously —
    all of them receive the same live updates.

Thread Safety:
    FastAPI runs on a single asyncio event loop, so plain dicts
    are safe here (no threading contention). All access is via
    async/await — no locks needed.
"""

import json
import logging
import uuid

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages active WebSocket connections, grouped by event_id.

    Usage:
        manager = ConnectionManager()
        await manager.connect(event_id, websocket)
        await manager.broadcast(event_id, payload_dict)
        manager.disconnect(event_id, websocket)
    """

    def __init__(self):
        # event_id (UUID) → set of WebSocket connections
        self._connections: dict[uuid.UUID, set[WebSocket]] = {}

    async def connect(self, event_id: uuid.UUID, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection for an event."""
        await websocket.accept()
        if event_id not in self._connections:
            self._connections[event_id] = set()
        self._connections[event_id].add(websocket)
        logger.info(
            f"WS connected: event={event_id} | "
            f"total connections for this event: {len(self._connections[event_id])}"
        )

    def disconnect(self, event_id: uuid.UUID, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from the registry."""
        if event_id in self._connections:
            self._connections[event_id].discard(websocket)
            if not self._connections[event_id]:
                del self._connections[event_id]
        logger.info(f"WS disconnected: event={event_id}")

    async def broadcast(self, event_id: uuid.UUID, payload: dict) -> None:
        """
        Push a JSON payload to ALL connected planners watching this event.

        If a specific connection is dead/broken, we silently remove it
        instead of crashing the broadcast loop.
        """
        connections = self._connections.get(event_id, set()).copy()
        if not connections:
            return

        dead_connections: list[WebSocket] = []
        message = json.dumps(payload, default=str)

        for ws in connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead_connections.append(ws)

        # Clean up any broken connections discovered during broadcast
        for ws in dead_connections:
            self.disconnect(event_id, ws)

    async def send_personal(self, websocket: WebSocket, payload: dict) -> None:
        """Send a payload to a single specific connection (used for initial_snapshot)."""
        try:
            await websocket.send_text(json.dumps(payload, default=str))
        except Exception as e:
            logger.warning(f"Failed to send personal WS message: {e}")

    def get_connection_count(self, event_id: uuid.UUID) -> int:
        """Return how many planners are watching a specific event."""
        return len(self._connections.get(event_id, set()))

    def get_total_connections(self) -> int:
        """Return total active WebSocket connections across all events."""
        return sum(len(conns) for conns in self._connections.values())


# Global singleton — imported by the WS endpoint and the Pub/Sub listener
manager = ConnectionManager()
