"""
Eventflow Cron Tasks — Celery Beat periodic jobs.

These tasks run on a schedule (configured in celery_app.py) and perform
automated maintenance that keeps the system consistent:

    1. hold_expiry_cleanup        — Every 2 min: releases ghost held-rooms
    2. waitlist_offer_expiry      — Every hour: expires stale waitlist offers
    3. booking_reminder_sequence  — Daily 9AM: sends reminder emails
    4. event_auto_completion      — Daily 8AM: completes events past hold_deadline

Architecture note:
    Celery Beat fires these tasks via Redis → Celery worker picks them up.
    All DB work uses the synchronous psycopg2 engine (same pattern as email_tasks.py)
    because Celery workers cannot safely share the asyncio event loop used by FastAPI.

    We wrap async service calls (promote_next) using asyncio.run() in a
    contained async context — the same pattern used by inventory_tasks.py.
"""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.celery_app import app
from app.config import settings

logger = logging.getLogger(__name__)

# ─── Synchronous DB engine (same pattern as email_tasks.py) ───────────────────
SYNC_DB_URL = settings.DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")
sync_engine = create_engine(SYNC_DB_URL, pool_pre_ping=True)
SyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)


# ══════════════════════════════════════════════════════════════════════════════
# CRON TASK 1: Hold Expiry Cleanup
# Schedule: Every 2 minutes (configured in celery_app.py)
# ══════════════════════════════════════════════════════════════════════════════

async def _async_hold_expiry_cleanup() -> int:
    """
    Scans for HELD bookings where hold_expires_at has passed.

    The Problem This Solves:
        A guest clicks "Book Now" → a HELD booking is created and held_rooms increments.
        The Redis layer-1 lock auto-expires after 15 minutes by TTL.
        BUT if the guest abandons (closes tab, loses internet), the PostgreSQL HELD
        booking record remains — permanently consuming capacity that no one owns.

        Without this cleanup:
            total=10, booked=8, held=2 (both ghosts) → available=0 → FULLY BOOKED ERROR
            But actually 2 rooms are free — they're just held by dead sessions!

    What we do per expired hold:
        1. Lock the allotment row (SELECT FOR UPDATE)
        2. Decrement held_rooms → restores the capacity
        3. Set booking status → EXPIRED
        4. Call promote_next() → if anyone is waitlisted, they get the freed slot
        5. COMMIT atomically → all changes in one transaction
    """
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
    from redis.asyncio import Redis as AsyncRedis
    from app.models.booking import Booking
    from app.models.room_block_allotment import RoomBlockAllotment
    from app.core.waitlists.service import promote_next
    from app.core.websockets.events import emit_hold_expired

    # Use the async engine for this async function
    async_engine = create_async_engine(settings.DATABASE_URL, echo=False)
    AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    # Dedicated Redis connection for dashboard emissions from Celery context
    redis = AsyncRedis.from_url(settings.REDIS_URL, decode_responses=True)

    released_count = 0
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Booking).where(
                Booking.status == "HELD",
                Booking.hold_expires_at <= now,
            )
        )
        expired_bookings = result.scalars().all()

        logger.info(f"hold_expiry_cleanup: found {len(expired_bookings)} expired holds to process")

        for booking in expired_bookings:
            try:
                # Lock allotment row — prevents race conditions with concurrent bookings
                allotment_result = await db.execute(
                    select(RoomBlockAllotment)
                    .where(RoomBlockAllotment.id == booking.allotment_id)
                    .with_for_update()
                )
                allotment = allotment_result.scalar_one()

                # Release the ghost hold
                if allotment.held_rooms > 0:
                    allotment.held_rooms -= 1
                allotment.version += 1

                booking.status = "EXPIRED"
                booking.hold_expires_at = None

                # Cascade: if someone is waitlisted for this room type, offer them the slot
                # promote_next flushes (does NOT commit) — we commit everything below
                await promote_next(
                    booking.room_block_id,
                    booking.room_type,
                    db,
                )

                await db.commit()
                released_count += 1
                logger.info(
                    f"  ✅ Released expired hold {booking.id} "
                    f"({booking.room_type}) — held_rooms now {allotment.held_rooms}"
                )

                # Phase 5: Dashboard emission (AFTER commit — fire-and-forget)
                await emit_hold_expired(
                    redis=redis,
                    event_id=booking.event_id,
                    room_type=booking.room_type,
                    allotment=allotment,
                )

            except Exception as e:
                await db.rollback()
                logger.error(f"  ❌ Failed to release hold {booking.id}: {e}")

    await redis.aclose()
    await async_engine.dispose()
    return released_count


@app.task
def hold_expiry_cleanup():
    """
    Celery Beat entry point for hold expiry cleanup.
    Runs every 2 minutes via the beat_schedule in celery_app.py.
    """
    logger.info("━━━ hold_expiry_cleanup START ━━━")
    released = asyncio.run(_async_hold_expiry_cleanup())
    logger.info(f"━━━ hold_expiry_cleanup DONE: {released} holds released ━━━")
    return {"released": released}


# ══════════════════════════════════════════════════════════════════════════════
# CRON TASK 2: Waitlist Offer Expiry
# Schedule: Top of every hour
# ══════════════════════════════════════════════════════════════════════════════

async def _async_waitlist_offer_expiry() -> int:
    """
    Scans for waitlist entries in "offered" state where offer_expires_at has passed.

    The Problem This Solves:
        When a booking is cancelled, promote_next() sets the next waitlisted guest's
        status to "offered" and sends them an email: "Book within 24 hours."

        But what if that guest also ignores the email?
        Without this task:
            - They stay in "offered" status permanently
            - Everyone BEHIND them on the waitlist never gets a chance
            - The room capacity sits in a weird limbo (not held, but the waitlist
              thinks it's spoken for)

    What we do per expired offer:
        1. Set waitlist entry status → "expired"
        2. Call promote_next() again → offer the room to the NEXT person in line
        3. COMMIT atomically
    """
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
    from app.models.waitlist import Waitlist
    from app.core.waitlists.service import promote_next

    async_engine = create_async_engine(settings.DATABASE_URL, echo=False)
    AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    expired_count = 0
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Waitlist).where(
                Waitlist.status == "offered",
                Waitlist.offer_expires_at <= now,
            )
        )
        expired_offers = result.scalars().all()

        logger.info(f"waitlist_offer_expiry: found {len(expired_offers)} stale offers to expire")

        for offer in expired_offers:
            try:
                offer.status = "expired"

                # Cascade to the next person in line
                await promote_next(offer.room_block_id, offer.room_type, db)

                await db.commit()
                expired_count += 1
                logger.info(f"  ✅ Expired offer {offer.id} for guest {offer.guest_id} ({offer.room_type})")

            except Exception as e:
                await db.rollback()
                logger.error(f"  ❌ Failed to expire offer {offer.id}: {e}")

    await async_engine.dispose()
    return expired_count


@app.task
def waitlist_offer_expiry():
    """
    Celery Beat entry point for waitlist offer expiry.
    Runs at the top of every hour via the beat_schedule in celery_app.py.
    """
    logger.info("━━━ waitlist_offer_expiry START ━━━")
    expired = asyncio.run(_async_waitlist_offer_expiry())
    logger.info(f"━━━ waitlist_offer_expiry DONE: {expired} offers expired ━━━")
    return {"expired": expired}


# ══════════════════════════════════════════════════════════════════════════════
# CRON TASK 3: Booking Reminder Sequence
# Schedule: Daily at 9 AM UTC
# ══════════════════════════════════════════════════════════════════════════════

async def _async_booking_reminder_sequence() -> int:
    """
    Scans all active events and sends targeted reminder emails to guests who
    haven't booked yet, at 7-day, 3-day, and 1-day intervals before event end.

    The Problem This Solves:
        After bulk import, 500 invitation emails are sent. People open them,
        think "I'll do this later", and forget. Without reminders:
            → Rooms go unclaimed
            → Hotel releases them back to public inventory on deadline
            → Corporate paid for 300 rooms, 80 were wasted
            → Finance asks questions nobody wants to answer

    Psychology of 3 touch-points (7-3-1 days):
        - 7 days: "Heads up, nothing urgent" — low friction
        - 3 days: "Running out of time" — creates urgency
        - 1 day:  "Final warning today" — FOMO, last chance

    We deliberately do NOT send daily reminders — that's spam and
    will cause guests to unsubscribe or ignore ALL future emails.

    What we do:
        1. Find all ACTIVE events whose end_date is exactly 7, 3, or 1 days away
        2. For each matching event, find all guests WITHOUT an active booking
        3. Dispatch send_booking_reminder_email Celery task for each guest
        (Tasks run async in background — this function returns fast)
    """
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
    from app.models.event import Event
    from app.models.guest import Guest
    from app.models.booking import Booking

    async_engine = create_async_engine(settings.DATABASE_URL, echo=False)
    AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    queued_count = 0
    today = date.today()

    async with AsyncSessionLocal() as db:
        # Only scan active events that are approaching (within 30 days)
        events_result = await db.execute(
            select(Event).where(
                Event.status == "active",
                Event.end_date >= today,
                Event.end_date <= today + timedelta(days=30),
            )
        )
        active_events = events_result.scalars().all()

        logger.info(f"booking_reminder_sequence: scanning {len(active_events)} active events")

        for event in active_events:
            days_left = (event.end_date - today).days

            # Only act on reminder milestones
            if days_left not in (7, 3, 1):
                continue

            logger.info(f"  Event '{event.name}' has {days_left} days left — sending reminders")

            # Subquery: guests who already have an active booking for this event
            booked_guest_ids_subquery = (
                select(Booking.guest_id).where(
                    Booking.event_id == event.id,
                    Booking.status.in_(["HELD", "CONFIRMED", "CHECKED_IN"]),
                )
            )

            # Find guests WITHOUT an active booking, who have emails
            unbooked_result = await db.execute(
                select(Guest).where(
                    Guest.event_id == event.id,
                    Guest.is_active == True,          # noqa: E712
                    Guest.email.isnot(None),           # can't email without address
                    ~Guest.id.in_(booked_guest_ids_subquery),
                )
            )
            unbooked_guests = unbooked_result.scalars().all()

            logger.info(
                f"  → {len(unbooked_guests)} guests haven't booked yet for '{event.name}'"
            )

            for guest in unbooked_guests:
                # Import here to avoid circular imports (email_tasks imports from models)
                from app.tasks.email_tasks import send_booking_reminder_email
                send_booking_reminder_email.delay(str(guest.id), days_left)
                queued_count += 1

    await async_engine.dispose()
    return queued_count


@app.task
def booking_reminder_sequence():
    """
    Celery Beat entry point for the booking reminder sequence.
    Runs daily at 9 AM UTC via the beat_schedule in celery_app.py.
    """
    logger.info("━━━ booking_reminder_sequence START ━━━")
    queued = asyncio.run(_async_booking_reminder_sequence())
    logger.info(f"━━━ booking_reminder_sequence DONE: {queued} reminder emails queued ━━━")
    return {"queued": queued}


# ══════════════════════════════════════════════════════════════════════════════
# CRON TASK 4: Event Auto-Completion
# Schedule: Daily at 8 AM UTC
#
# The Real-World Problem:
#     When the booking deadline passes, nothing happens. The planner has to
#     remember to download the rooming list and send it to the hotel manually.
#     If they forget, the hotel has no confirmed numbers 2 days before check-in.
#     This happens constantly in real group travel management.
#
# What This Task Does:
#     1. Find events where ALL room blocks have hold_deadline in the past
#     2. For each: release unclaimed rooms back to hotel inventory
#     3. Mark room blocks as "released", event as "completed"
#     4. Email planner with final summary (X confirmed, Y released)
#     5. Email hotel venue contact with rooming list summary
#     6. Emit WebSocket event_completed so live dashboards update
# ══════════════════════════════════════════════════════════════════════════════

async def _async_event_auto_completion() -> int:
    """
    Scans for active events whose room block hold_deadlines have ALL passed.
    For each matching event, performs the full completion flow.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
    from sqlalchemy.orm import selectinload
    from redis.asyncio import Redis as AsyncRedis
    from app.models.event import Event
    from app.models.room_block import RoomBlock
    from app.models.room_block_allotment import RoomBlockAllotment
    from app.models.venue import Venue
    from app.models.user import User
    from app.core.websockets.events import _safe_publish

    async_engine = create_async_engine(settings.DATABASE_URL, echo=False)
    AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    redis = AsyncRedis.from_url(settings.REDIS_URL, decode_responses=True)

    completed_count = 0
    today = date.today()

    async with AsyncSessionLocal() as db:
        # Find all active events
        events_result = await db.execute(
            select(Event).where(Event.status == "active")
        )
        active_events = events_result.scalars().all()

        logger.info(f"event_auto_completion: scanning {len(active_events)} active events")

        for event in active_events:
            try:
                # Load all room blocks for this event
                blocks_result = await db.execute(
                    select(RoomBlock)
                    .options(selectinload(RoomBlock.allotments))
                    .where(
                        RoomBlock.event_id == event.id,
                        RoomBlock.status == "confirmed",
                    )
                )
                blocks = blocks_result.scalars().all()

                if not blocks:
                    continue

                # Check: ALL blocks must have hold_deadline in the past
                all_past = all(block.hold_deadline < today for block in blocks)
                if not all_past:
                    continue

                logger.info(f"  🏁 Event '{event.name}' — all deadlines passed, completing...")

                total_confirmed = 0
                total_released = 0
                room_breakdown = []

                for block in blocks:
                    # Load venue for hotel contact email
                    venue_result = await db.execute(
                        select(Venue).where(Venue.id == block.venue_id)
                    )
                    venue = venue_result.scalar_one_or_none()

                    for allotment in block.allotments:
                        # Lock allotment for update
                        locked_result = await db.execute(
                            select(RoomBlockAllotment)
                            .where(RoomBlockAllotment.id == allotment.id)
                            .with_for_update()
                        )
                        locked_allotment = locked_result.scalar_one()

                        booked = locked_allotment.booked_rooms
                        released = locked_allotment.total_rooms - locked_allotment.booked_rooms

                        # Release any remaining held rooms (shouldn't be any after cron 1, but safety)
                        locked_allotment.held_rooms = 0
                        locked_allotment.version += 1

                        total_confirmed += booked
                        total_released += released

                        room_breakdown.append({
                            "room_type": locked_allotment.room_type,
                            "booked": booked,
                            "released": released,
                            "total": locked_allotment.total_rooms,
                        })

                    # Mark block as released
                    block.status = "released"

                    # Build summary data for emails
                    venue_name = venue.name if venue else "the venue"
                    venue_email = venue.contact_email if venue else None

                    summary_data = {
                        "confirmed_rooms": total_confirmed,
                        "released_rooms": total_released,
                        "room_breakdown": room_breakdown,
                        "venue_name": venue_name,
                        "check_in_date": str(block.check_in_date),
                        "check_out_date": str(block.check_out_date),
                    }

                # Mark event as completed
                event.status = "completed"

                await db.commit()
                completed_count += 1

                logger.info(
                    f"  ✅ Event '{event.name}' completed: "
                    f"{total_confirmed} confirmed, {total_released} released"
                )

                # ── Post-commit actions (fire-and-forget) ──

                # Find planner email for hotel handoff
                planner_result = await db.execute(
                    select(User).where(
                        User.tenant_id == event.tenant_id,
                        User.role.in_(["admin", "planner"]),
                        User.is_active == True,
                    )
                )
                planner = planner_result.scalars().first()
                planner_email = planner.email if planner else ""

                summary_data["planner_email"] = planner_email

                # Email planner
                from app.tasks.email_tasks import send_event_completion_email
                send_event_completion_email.delay(str(event.id), summary_data)

                # Email hotel (only if venue has a contact_email)
                if venue_email:
                    from app.tasks.email_tasks import send_hotel_handoff_email
                    send_hotel_handoff_email.delay(str(event.id), venue_email, summary_data)

                # WebSocket: emit event_completed
                await _safe_publish(redis, event.id, {
                    "type": "event_completed",
                    "event_name": event.name,
                    "confirmed_rooms": total_confirmed,
                    "released_rooms": total_released,
                    "room_breakdown": room_breakdown,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            except Exception as e:
                await db.rollback()
                logger.error(f"  ❌ Failed to complete event '{event.name}': {e}")

    await redis.aclose()
    await async_engine.dispose()
    return completed_count


@app.task
def event_auto_completion():
    """
    Celery Beat entry point for event auto-completion.
    Runs daily at 8 AM UTC via the beat_schedule in celery_app.py.
    """
    logger.info("━━━ event_auto_completion START ━━━")
    completed = asyncio.run(_async_event_auto_completion())
    logger.info(f"━━━ event_auto_completion DONE: {completed} events completed ━━━")
    return {"completed": completed}
