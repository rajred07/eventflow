"""
Analytics Engine — demand forecasting and dashboard intelligence.

Provides the data that powers the planner dashboard:
    1. Inventory snapshot (all room blocks with booked/held/available)
    2. Guest status breakdown (confirmed/pending/waitlisted/cancelled)
    3. Budget consumption overview
    4. Booking velocity (rooms booked per day)
    5. Stockout prediction (when will each room type be full)
    6. Recent activity feed (last N booking lifecycle events)
    7. Category demographics (which guest categories are booking fastest)

Design:
    All functions are pure database reads — no side effects.
    They accept a db session and return plain dicts (serialized by
    the Pydantic schemas in schemas/analytics.py).
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import case, cast, Date, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking
from app.models.event import Event
from app.models.guest import Guest
from app.models.room_block import RoomBlock
from app.models.room_block_allotment import RoomBlockAllotment
from app.models.waitlist import Waitlist
from app.models.wallet import Wallet, WalletTransaction


async def get_inventory_snapshot(
    event_id: uuid.UUID,
    db: AsyncSession,
) -> list[dict]:
    """
    For every room type across all blocks of this event, return:
    total_rooms, booked_rooms, held_rooms, available, waitlist_count.
    """
    # Get all allotments for this event's blocks
    allotment_query = (
        select(RoomBlockAllotment)
        .join(RoomBlock, RoomBlock.id == RoomBlockAllotment.room_block_id)
        .where(RoomBlock.event_id == event_id, RoomBlock.status == "confirmed")
    )
    result = await db.execute(allotment_query)
    allotments = result.scalars().all()

    # Get waitlist counts per room_type
    waitlist_counts_query = (
        select(
            Waitlist.room_type,
            func.count(Waitlist.id).label("waitlist_count"),
        )
        .where(
            Waitlist.event_id == event_id,
            Waitlist.status.in_(["waiting", "offered"]),
        )
        .group_by(Waitlist.room_type)
    )
    wl_result = await db.execute(waitlist_counts_query)
    wl_map = {row.room_type: row.waitlist_count for row in wl_result.all()}

    inventory = []
    for a in allotments:
        available = a.total_rooms - a.booked_rooms - a.held_rooms
        utilization = (a.booked_rooms / a.total_rooms * 100) if a.total_rooms > 0 else 0
        inventory.append({
            "room_block_id": str(a.room_block_id),
            "room_type": a.room_type,
            "total_rooms": a.total_rooms,
            "booked_rooms": a.booked_rooms,
            "held_rooms": a.held_rooms,
            "available": max(available, 0),
            "waitlist_count": wl_map.get(a.room_type, 0),
            "utilization_pct": round(utilization, 1),
            "negotiated_rate": float(a.negotiated_rate),
        })

    return inventory


async def get_guest_status_breakdown(
    event_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """
    Returns guest counts by booking status:
    total_invited, confirmed, pending (no booking), waitlisted, cancelled.
    """
    # Total active guests
    total_q = select(func.count(Guest.id)).where(
        Guest.event_id == event_id, Guest.is_active == True  # noqa: E712
    )
    total_invited = (await db.execute(total_q)).scalar() or 0

    # Guests with confirmed bookings
    confirmed_q = select(func.count(func.distinct(Booking.guest_id))).where(
        Booking.event_id == event_id,
        Booking.status.in_(["CONFIRMED", "CHECKED_IN"]),
    )
    confirmed = (await db.execute(confirmed_q)).scalar() or 0

    # Guests with active holds
    held_q = select(func.count(func.distinct(Booking.guest_id))).where(
        Booking.event_id == event_id,
        Booking.status == "HELD",
    )
    held = (await db.execute(held_q)).scalar() or 0

    # Guests on waitlist
    waitlisted_q = select(func.count(func.distinct(Waitlist.guest_id))).where(
        Waitlist.event_id == event_id,
        Waitlist.status.in_(["waiting", "offered"]),
    )
    waitlisted = (await db.execute(waitlisted_q)).scalar() or 0

    # Guests who cancelled
    cancelled_q = select(func.count(func.distinct(Booking.guest_id))).where(
        Booking.event_id == event_id,
        Booking.status == "CANCELLED",
    )
    cancelled = (await db.execute(cancelled_q)).scalar() or 0

    # Pending = invited but no active booking/waitlist
    pending = total_invited - confirmed - held - waitlisted - cancelled
    pending = max(pending, 0)

    return {
        "total_invited": total_invited,
        "confirmed": confirmed,
        "held": held,
        "pending": pending,
        "waitlisted": waitlisted,
        "cancelled": cancelled,
    }


async def get_budget_overview(
    event_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """
    Aggregate wallet data: total loaded, total spent, remaining, avg per booking.
    """
    # Total credits loaded into wallets for this event
    total_loaded_q = select(func.sum(WalletTransaction.amount)).join(Wallet).where(
        Wallet.event_id == event_id,
        Wallet.tenant_id == tenant_id,
        WalletTransaction.type == "credit",
    )
    total_loaded = (await db.execute(total_loaded_q)).scalar() or Decimal("0.00")

    # Total debits (subsidies applied)
    total_spent_q = select(func.sum(WalletTransaction.amount)).join(Wallet).where(
        Wallet.event_id == event_id,
        Wallet.tenant_id == tenant_id,
        WalletTransaction.type == "debit",
    )
    total_spent = (await db.execute(total_spent_q)).scalar() or Decimal("0.00")

    remaining = total_loaded - total_spent

    # Average subsidy per confirmed booking
    confirmed_count_q = select(func.count(Booking.id)).where(
        Booking.event_id == event_id,
        Booking.status.in_(["CONFIRMED", "CHECKED_IN"]),
    )
    confirmed_count = (await db.execute(confirmed_count_q)).scalar() or 0

    avg_per_booking = (
        float(total_spent / confirmed_count) if confirmed_count > 0 else 0.0
    )

    # Projected final spend: (avg_per_booking * total_invited)
    total_invited_q = select(func.count(Guest.id)).where(
        Guest.event_id == event_id, Guest.is_active == True  # noqa: E712
    )
    total_invited = (await db.execute(total_invited_q)).scalar() or 0
    projected_spend = avg_per_booking * total_invited if avg_per_booking > 0 else 0.0

    pct_consumed = (
        float(total_spent / total_loaded * 100) if total_loaded > 0 else 0.0
    )

    return {
        "total_loaded": float(total_loaded),
        "total_spent": float(total_spent),
        "remaining": float(remaining),
        "avg_per_booking": round(avg_per_booking, 2),
        "projected_final_spend": round(projected_spend, 2),
        "percentage_consumed": round(pct_consumed, 1),
        "confirmed_bookings": confirmed_count,
    }


async def get_booking_velocity(
    event_id: uuid.UUID,
    db: AsyncSession,
    lookback_days: int = 30,
) -> list[dict]:
    """
    Bookings per day for the last N days. Powers the velocity chart.
    Returns [{date: "2026-03-28", count: 12}, ...] sorted ascending.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    velocity_q = (
        select(
            cast(Booking.created_at, Date).label("booking_date"),
            func.count(Booking.id).label("count"),
        )
        .where(
            Booking.event_id == event_id,
            Booking.status.in_(["CONFIRMED", "CHECKED_IN"]),
            Booking.created_at >= cutoff,
        )
        .group_by(cast(Booking.created_at, Date))
        .order_by(cast(Booking.created_at, Date))
    )

    result = await db.execute(velocity_q)
    return [
        {"date": str(row.booking_date), "count": row.count}
        for row in result.all()
    ]


async def get_stockout_prediction(
    event_id: uuid.UUID,
    db: AsyncSession,
) -> list[dict]:
    """
    For each room type, predict when it will be fully booked based on
    the recent booking velocity (last 7 days average).

    Returns:
        [
            {
                "room_type": "standard",
                "status": "FULL" | "WARNING" | "ON_TRACK",
                "utilization_pct": 82.5,
                "projected_full_date": "2026-04-10" | null,
                "days_until_full": 6 | null,
                "recommendation": "Consider expanding block" | null
            },
            ...
        ]
    """
    inventory = await get_inventory_snapshot(event_id, db)

    # Get the event deadline
    event_q = select(Event.end_date, Event.start_date).where(Event.id == event_id)
    event_result = await db.execute(event_q)
    event_row = event_result.first()
    if not event_row:
        return []
    event_deadline = event_row.end_date

    # Calculate velocity per room type over last 7 days
    cutoff_7d = datetime.now(timezone.utc) - timedelta(days=7)

    velocity_by_type_q = (
        select(
            Booking.room_type,
            func.count(Booking.id).label("bookings_7d"),
        )
        .where(
            Booking.event_id == event_id,
            Booking.status.in_(["CONFIRMED", "CHECKED_IN"]),
            Booking.created_at >= cutoff_7d,
        )
        .group_by(Booking.room_type)
    )
    vel_result = await db.execute(velocity_by_type_q)
    vel_map = {row.room_type: row.bookings_7d for row in vel_result.all()}

    predictions = []
    today = date.today()

    for block in inventory:
        room_type = block["room_type"]
        available = block["available"]
        utilization = block["utilization_pct"]
        bookings_7d = vel_map.get(room_type, 0)

        # Daily velocity (rooms booked per day over the last 7 days)
        daily_velocity = bookings_7d / 7.0 if bookings_7d > 0 else 0

        if available <= 0:
            predictions.append({
                "room_type": room_type,
                "status": "FULL",
                "utilization_pct": utilization,
                "daily_velocity": round(daily_velocity, 1),
                "projected_full_date": None,
                "days_until_full": None,
                "recommendation": f"{block['waitlist_count']} guests waitlisted. Consider expanding block.",
            })
        elif daily_velocity > 0:
            days_to_full = available / daily_velocity
            projected_date = today + timedelta(days=int(days_to_full))

            if projected_date <= event_deadline:
                status = "WARNING" if utilization >= 80 else "ON_TRACK"
                recommendation = None
                if utilization >= 80:
                    recommendation = (
                        f"Projected full by {projected_date.isoformat()} — "
                        f"{int(days_to_full)} days. Consider action."
                    )
            else:
                status = "ON_TRACK"
                recommendation = (
                    f"At current pace, only {round(utilization + (daily_velocity / block['total_rooms'] * 100 * (event_deadline - today).days), 1)}% "
                    f"filled by deadline."
                )

            predictions.append({
                "room_type": room_type,
                "status": status,
                "utilization_pct": utilization,
                "daily_velocity": round(daily_velocity, 1),
                "projected_full_date": projected_date.isoformat(),
                "days_until_full": int(days_to_full),
                "recommendation": recommendation,
            })
        else:
            # No bookings in the last 7 days
            predictions.append({
                "room_type": room_type,
                "status": "ON_TRACK",
                "utilization_pct": utilization,
                "daily_velocity": 0,
                "projected_full_date": None,
                "days_until_full": None,
                "recommendation": "No bookings in the last 7 days. Consider sending reminders.",
            })

    return predictions


async def get_category_demographics(
    event_id: uuid.UUID,
    db: AsyncSession,
) -> list[dict]:
    """
    Which guest categories are booking fastest.
    Returns: [{category: "vip", total: 50, booked: 45, pct: 90.0}, ...]
    """
    # Total guests per category
    total_q = (
        select(
            Guest.category,
            func.count(Guest.id).label("total"),
        )
        .where(Guest.event_id == event_id, Guest.is_active == True)  # noqa: E712
        .group_by(Guest.category)
    )
    total_result = await db.execute(total_q)
    totals = {row.category: row.total for row in total_result.all()}

    # Booked guests per category
    booked_q = (
        select(
            Guest.category,
            func.count(func.distinct(Booking.guest_id)).label("booked"),
        )
        .join(Booking, Booking.guest_id == Guest.id)
        .where(
            Booking.event_id == event_id,
            Booking.status.in_(["CONFIRMED", "CHECKED_IN"]),
        )
        .group_by(Guest.category)
    )
    booked_result = await db.execute(booked_q)
    booked_map = {row.category: row.booked for row in booked_result.all()}

    demographics = []
    for category, total in totals.items():
        booked = booked_map.get(category, 0)
        pct = round(booked / total * 100, 1) if total > 0 else 0.0
        demographics.append({
            "category": category,
            "total_guests": total,
            "booked": booked,
            "booking_rate_pct": pct,
        })

    # Sort by booking rate descending (fastest-booking category first)
    demographics.sort(key=lambda x: x["booking_rate_pct"], reverse=True)
    return demographics


async def get_recent_activity(
    event_id: uuid.UUID,
    db: AsyncSession,
    limit: int = 10,
) -> list[dict]:
    """
    Last N booking lifecycle events for the live feed.
    Returns newest-first list of recent booking actions.
    """
    # Recent bookings (all statuses, ordered by updated_at desc)
    recent_q = (
        select(Booking, Guest.name.label("guest_name"))
        .join(Guest, Guest.id == Booking.guest_id)
        .where(Booking.event_id == event_id)
        .order_by(Booking.updated_at.desc())
        .limit(limit)
    )
    result = await db.execute(recent_q)

    activity = []
    for booking, guest_name in result.all():
        # Map DB status to human-readable action
        action_map = {
            "HELD": "created a hold",
            "CONFIRMED": "confirmed",
            "CANCELLED": "cancelled",
            "EXPIRED": "hold expired",
            "CHECKED_IN": "checked in",
            "CHECKED_OUT": "checked out",
        }
        action = action_map.get(booking.status, booking.status)

        activity.append({
            "guest_name": guest_name,
            "action": action,
            "room_type": booking.room_type,
            "num_nights": booking.num_nights,
            "status": booking.status,
            "timestamp": booking.updated_at.isoformat() if booking.updated_at else None,
        })

    return activity


async def get_dashboard_snapshot(
    event_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """
    The complete dashboard snapshot pushed on WebSocket connect.
    Combines inventory, budget, guest status, and recent activity into
    a single payload so the frontend is perfectly synchronized from
    the first millisecond.
    """
    inventory = await get_inventory_snapshot(event_id, db)
    guest_status = await get_guest_status_breakdown(event_id, db)
    budget = await get_budget_overview(event_id, tenant_id, db)
    recent_activity = await get_recent_activity(event_id, db, limit=10)

    return {
        "type": "initial_snapshot",
        "inventory": inventory,
        "guest_status": guest_status,
        "budget": budget,
        "recent_activity": recent_activity,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
