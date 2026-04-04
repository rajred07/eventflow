"""
Dashboard Event Emission Helper — publishes live updates to Redis Pub/Sub.

This module is the ONLY integration point between the core transactional
services (bookings, waitlists, cron tasks) and the live dashboard.

Design Rules:
    1. Every emit function is fire-and-forget. If Redis is down, the booking
       still succeeds — we log the error and move on.
    2. Emit calls happen AFTER db.commit(). They never interfere with the
       transaction. If the emit fails, the data is already safely committed.
    3. Each payload includes a full inventory_snapshot so the frontend
       doesn't need to make a follow-up HTTP call to reconcile.

Channel Format:
    event:{event_id}:updates

    The Pub/Sub listener in pubsub.py subscribes to "event:*:updates"
    and routes each message to the correct WebSocket connections.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# The channel pattern used by all dashboard emissions.
# The pubsub listener subscribes to "event:*:updates" (pattern subscribe).
CHANNEL_TEMPLATE = "event:{event_id}:updates"


async def _safe_publish(redis: Redis, event_id: uuid.UUID, payload: dict) -> None:
    """
    Publish a JSON payload to the event's Redis channel.
    Wrapped in try/except so a Redis failure never crashes the caller.
    """
    channel = CHANNEL_TEMPLATE.format(event_id=str(event_id))
    try:
        await redis.publish(channel, json.dumps(payload, default=str))
        logger.debug(f"📡 Published {payload.get('type')} to {channel}")
    except Exception as e:
        logger.warning(f"⚠️ Failed to publish dashboard event to {channel}: {e}")


def _inventory_snapshot(allotment) -> dict:
    """Build a standardized inventory snapshot from an allotment row."""
    return {
        "room_type": allotment.room_type,
        "total_rooms": allotment.total_rooms,
        "booked_count": allotment.booked_rooms,
        "held_count": allotment.held_rooms,
        "available": allotment.total_rooms - allotment.booked_rooms - allotment.held_rooms,
    }


# ---------------------------------------------------------------------------
# Booking Events
# ---------------------------------------------------------------------------


async def emit_hold_created(
    redis: Redis,
    event_id: uuid.UUID,
    guest_name: str,
    room_type: str,
    allotment: Any,
) -> None:
    """Emitted by create_hold() after successful DB commit."""
    await _safe_publish(redis, event_id, {
        "type": "hold_created",
        "guest_name": guest_name,
        "room_type": room_type,
        "inventory_snapshot": _inventory_snapshot(allotment),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


async def emit_booking_confirmed(
    redis: Redis,
    event_id: uuid.UUID,
    guest_name: str,
    room_type: str,
    allotment: Any,
    subsidy_applied: float = 0.0,
    total_cost: float = 0.0,
    num_nights: int = 0,
) -> None:
    """Emitted by confirm_hold() after successful DB commit."""
    await _safe_publish(redis, event_id, {
        "type": "booking_confirmed",
        "guest_name": guest_name,
        "room_type": room_type,
        "num_nights": num_nights,
        "total_cost": float(total_cost),
        "subsidy_applied": float(subsidy_applied),
        "inventory_snapshot": _inventory_snapshot(allotment),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


async def emit_booking_cancelled(
    redis: Redis,
    event_id: uuid.UUID,
    guest_name: str,
    room_type: str,
    allotment: Any,
    refund_amount: float = 0.0,
) -> None:
    """Emitted by cancel_booking() after successful DB commit."""
    await _safe_publish(redis, event_id, {
        "type": "booking_cancelled",
        "guest_name": guest_name,
        "room_type": room_type,
        "refund_amount": float(refund_amount),
        "inventory_snapshot": _inventory_snapshot(allotment),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


# ---------------------------------------------------------------------------
# Waitlist Events
# ---------------------------------------------------------------------------


async def emit_waitlist_joined(
    redis: Redis,
    event_id: uuid.UUID,
    guest_name: str,
    room_type: str,
) -> None:
    """Emitted when a guest joins the waitlist."""
    await _safe_publish(redis, event_id, {
        "type": "waitlist_joined",
        "guest_name": guest_name,
        "room_type": room_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


async def emit_waitlist_promoted(
    redis: Redis,
    event_id: uuid.UUID,
    guest_name: str,
    room_type: str,
) -> None:
    """Emitted when a waitlisted guest is offered a room."""
    await _safe_publish(redis, event_id, {
        "type": "waitlist_promoted",
        "guest_name": guest_name,
        "room_type": room_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


# ---------------------------------------------------------------------------
# Cron / Hold Expiry Events
# ---------------------------------------------------------------------------


async def emit_hold_expired(
    redis: Redis,
    event_id: uuid.UUID,
    room_type: str,
    allotment: Any,
) -> None:
    """Emitted by the hold_expiry_cleanup cron task."""
    await _safe_publish(redis, event_id, {
        "type": "hold_expired",
        "room_type": room_type,
        "inventory_snapshot": _inventory_snapshot(allotment),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


# ---------------------------------------------------------------------------
# Threshold Alert Events
# ---------------------------------------------------------------------------


async def emit_threshold_alert(
    redis: Redis,
    event_id: uuid.UUID,
    alert_type: str,
    room_type: str | None,
    percentage: float,
    message: str,
) -> None:
    """
    Emitted when a room block or budget crosses a critical threshold.

    alert_type examples:
        "block_threshold_80", "block_threshold_95",
        "budget_80_consumed", "deadline_24h"
    """
    await _safe_publish(redis, event_id, {
        "type": alert_type,
        "room_type": room_type,
        "percentage": round(percentage, 1),
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
