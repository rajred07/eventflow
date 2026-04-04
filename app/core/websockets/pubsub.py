"""
Redis Pub/Sub Listener — bridges Redis channels to WebSocket connections.

Architecture:
    This runs as a long-lived asyncio background task started when FastAPI
    boots up (via the lifespan context manager in main.py).

    It subscribes to the Redis pattern "event:*:updates" and whenever
    ANY service (booking, waitlist, cron worker) publishes to a channel
    like "event:abc-123:updates", this listener:
        1. Extracts the event_id from the channel name
        2. Parses the JSON payload
        3. Calls manager.broadcast(event_id, payload)
        4. The ConnectionManager pushes it to every connected planner

    This decouples the transactional services entirely from WebSocket
    management. The booking service just does redis.publish() and moves on.

Why Pattern Subscribe:
    We use PSUBSCRIBE with "event:*:updates" instead of subscribing to
    individual channels. This means a single listener handles ALL events.
    When a new event starts getting bookings, we don't need to manually
    subscribe — it's already covered by the wildcard.
"""

import asyncio
import json
import logging
import uuid

from redis.asyncio import ConnectionPool, Redis

from app.config import settings
from app.core.websockets.manager import manager

logger = logging.getLogger(__name__)

# Dedicated Redis connection for Pub/Sub (separate from the main pool
# because Pub/Sub connections cannot be shared with regular commands).
_pubsub_pool = ConnectionPool.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    max_connections=5,
)


def _extract_event_id(channel: str) -> uuid.UUID | None:
    """
    Extract the event UUID from a channel name like "event:abc-def-123:updates".
    Returns None if the channel format is unexpected.
    """
    try:
        # channel = "event:{uuid}:updates"
        parts = channel.split(":")
        if len(parts) == 3 and parts[0] == "event" and parts[2] == "updates":
            return uuid.UUID(parts[1])
    except (ValueError, IndexError):
        pass
    return None


async def start_pubsub_listener() -> None:
    """
    Long-running coroutine that listens to Redis Pub/Sub and forwards
    messages to WebSocket connections via the ConnectionManager.

    This function runs forever (until cancelled). It auto-reconnects
    on Redis failures with exponential backoff.
    """
    retry_delay = 1  # seconds, will increase on consecutive failures

    while True:
        redis_client = Redis(connection_pool=_pubsub_pool)
        pubsub = redis_client.pubsub()

        try:
            # Pattern subscribe — catches ALL event channels
            await pubsub.psubscribe("event:*:updates")
            logger.info("📡 Redis Pub/Sub listener started — subscribed to event:*:updates")
            retry_delay = 1  # Reset backoff on successful connect

            async for message in pubsub.listen():
                if message["type"] != "pmessage":
                    continue

                channel = message.get("channel", "")
                data = message.get("data", "")

                event_id = _extract_event_id(channel)
                if event_id is None:
                    logger.warning(f"Could not parse event_id from channel: {channel}")
                    continue

                # Only broadcast if someone is actually watching
                if manager.get_connection_count(event_id) == 0:
                    continue

                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON on channel {channel}: {data[:100]}")
                    continue

                await manager.broadcast(event_id, payload)

        except asyncio.CancelledError:
            logger.info("📡 Pub/Sub listener shutting down (cancelled)")
            await pubsub.punsubscribe("event:*:updates")
            await pubsub.close()
            await redis_client.aclose()
            return

        except Exception as e:
            logger.error(f"📡 Pub/Sub listener error: {e} — reconnecting in {retry_delay}s")
            try:
                await pubsub.close()
                await redis_client.aclose()
            except Exception:
                pass
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30)  # Cap at 30s
