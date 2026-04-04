"""
Threshold Checker — detects when room blocks or budgets cross critical levels.

This is called AFTER a booking event emission. If the updated inventory
pushes a room block past 80% or 95%, or the budget past 80%, an additional
alert event is emitted to the dashboard.

Design:
    This function does NOT query the database. It operates on the
    allotment object already loaded in memory by the booking service.
    Zero additional DB round-trips.
"""

import uuid

from redis.asyncio import Redis

from app.core.websockets.events import emit_threshold_alert


async def check_block_thresholds(
    redis: Redis,
    event_id: uuid.UUID,
    allotment,
) -> None:
    """
    Check if the allotment just crossed 80% or 95% utilization.
    Emits alert events if thresholds are breached.

    Called after create_hold() and confirm_hold() emit their primary events.
    """
    if allotment.total_rooms <= 0:
        return

    utilization = (allotment.booked_rooms + allotment.held_rooms) / allotment.total_rooms
    pct = round(utilization * 100, 1)

    # 95% threshold — urgent
    if pct >= 95:
        await emit_threshold_alert(
            redis=redis,
            event_id=event_id,
            alert_type="block_threshold_95",
            room_type=allotment.room_type,
            percentage=pct,
            message=(
                f"🔴 URGENT: {allotment.room_type.title()} rooms are {pct}% utilized. "
                f"Only {allotment.total_rooms - allotment.booked_rooms - allotment.held_rooms} "
                f"remaining."
            ),
        )
    # 80% threshold — warning
    elif pct >= 80:
        await emit_threshold_alert(
            redis=redis,
            event_id=event_id,
            alert_type="block_threshold_80",
            room_type=allotment.room_type,
            percentage=pct,
            message=(
                f"⚠️ {allotment.room_type.title()} rooms are {pct}% utilized. "
                f"{allotment.total_rooms - allotment.booked_rooms - allotment.held_rooms} "
                f"rooms still available."
            ),
        )


async def check_budget_thresholds(
    redis: Redis,
    event_id: uuid.UUID,
    total_loaded: float,
    total_spent: float,
) -> None:
    """
    Check if corporate budget crossed the 80% consumption threshold.
    Called after confirm_hold() applies a wallet subsidy.
    """
    if total_loaded <= 0:
        return

    pct = round(total_spent / total_loaded * 100, 1)

    if pct >= 80:
        await emit_threshold_alert(
            redis=redis,
            event_id=event_id,
            alert_type="budget_80_consumed",
            room_type=None,
            percentage=pct,
            message=(
                f"💰 Corporate budget is {pct}% consumed. "
                f"₹{total_loaded - total_spent:,.0f} remaining."
            ),
        )
