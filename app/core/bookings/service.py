"""
Booking Service — the transactional core of Eventflow.

Implements the two-tier locking strategy:
Layer 1: Redis hold (NX EX 900) prevents two guests from entering the payment flow.
Layer 2: PostgreSQL row lock (FOR UPDATE) commits the reservation.

Phase 5 Addition:
    After every successful db.commit(), we emit a dashboard event via Redis
    Pub/Sub. These emissions are fire-and-forget — if Redis Pub/Sub is down,
    the booking still succeeds. The WebSocket layer is fully decoupled.
"""

import uuid
import logging
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.waitlists.service import promote_next
from app.core.wallets.service import credit_on_cancellation, debit_on_booking
from app.core.websockets.events import (
    emit_hold_created,
    emit_booking_confirmed,
    emit_booking_cancelled,
)
from app.core.analytics.thresholds import check_block_thresholds, check_budget_thresholds
from app.models.booking import Booking
from app.models.guest import Guest
from app.models.room_block import RoomBlock
from app.models.room_block_allotment import RoomBlockAllotment
from app.models.wallet import Wallet, WalletTransaction
from app.schemas.booking import BookingHoldRequest
from app.tasks.email_tasks import send_booking_confirmation_email, send_waitlist_offer_email

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step 1: Create Hold
# ---------------------------------------------------------------------------


async def create_hold(
    data: BookingHoldRequest,
    db: AsyncSession,
    redis: Redis,
) -> Booking:
    """
    Step 1 of the Booking Flow.
    The guest clicked "Book Now". We use their magic-link token to identify them.
    We try to get a 15-minute lock in Redis. If successful, we update PG to reflect
    the held room and return a HELD booking record.
    """
    # 1. Identify guest via token (no auth required for public microsite)
    guest_result = await db.execute(
        select(Guest).where(
            Guest.booking_token == data.guest_token, Guest.is_active == True
        )
    )
    guest = guest_result.scalar_one_or_none()
    if not guest:
        raise ValueError("Invalid or inactive guest token.")

    # 2. Check if guest already has a non-cancelled booking for this event
    existing_booking = await db.execute(
        select(Booking.id).where(
            Booking.guest_id == guest.id,
            Booking.event_id == guest.event_id,
            Booking.status.in_(["HELD", "CONFIRMED", "CHECKED_IN"]),
        )
    )
    if existing_booking.scalar_one_or_none():
        raise ValueError("You already have an active reservation for this event.")

    # 3. Get generic block info
    block_result = await db.execute(
        select(RoomBlock).where(RoomBlock.id == data.room_block_id)
    )
    block = block_result.scalar_one_or_none()
    if not block or block.event_id != guest.event_id:
        raise ValueError("Room block not found or does not belong to your event.")

    # 4. Redis Layer-1 Lock
    lock_key = f"hold:{block.id}:{data.room_type}:{guest.id}"
    lock_acquired = await redis.set(lock_key, str(guest.id), nx=True, ex=900)
    
    if not lock_acquired:
        raise ValueError("You are already holding a room. Please complete or wait 15 min.")

    try:
        # 5. PostgreSQL Layer-2 Fast Update
        allotment_result = await db.execute(
            select(RoomBlockAllotment)
            .where(
                RoomBlockAllotment.room_block_id == block.id,
                RoomBlockAllotment.room_type == data.room_type,
            )
            .with_for_update()  # Locks ONLY this specific room type row
        )
        allotment = allotment_result.scalar_one_or_none()
        
        if not allotment:
            raise ValueError("Room type not found in this block.")

        # Check availability
        available = allotment.total_rooms - (allotment.booked_rooms + allotment.held_rooms)
        if available <= 0:
            raise ValueError("Room type is fully booked. Please join the waitlist.")

        # Assign the hold
        allotment.held_rooms += 1
        allotment.version += 1
        
        # Calculate financials (simplified for Phase 2 without Wallet yet)
        num_nights = (block.check_out_date - block.check_in_date).days
        total_cost = float(allotment.negotiated_rate) * num_nights

        booking = Booking(
            tenant_id=block.tenant_id,
            event_id=block.event_id,
            guest_id=guest.id,
            room_block_id=block.id,
            allotment_id=allotment.id,
            room_type=data.room_type,
            check_in_date=block.check_in_date,
            check_out_date=block.check_out_date,
            num_nights=num_nights,
            room_rate_per_night=float(allotment.negotiated_rate),
            total_cost=total_cost,
            subsidy_applied=0.00,  # Hooked into Wallet in Phase 2D
            amount_due=total_cost,
            status="HELD",
            hold_expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
        db.add(booking)
        await db.commit()
        await db.refresh(booking)

        # ── Phase 5: Dashboard Emission (AFTER commit — fire-and-forget) ──
        await emit_hold_created(
            redis=redis,
            event_id=block.event_id,
            guest_name=guest.name,
            room_type=data.room_type,
            allotment=allotment,
        )
        await check_block_thresholds(redis, block.event_id, allotment)

        return booking

    except Exception as e:
        # Rollback db and redis if anything failed during DB stage
        await db.rollback()
        await redis.delete(lock_key)
        raise e


# ---------------------------------------------------------------------------
# Step 2: Confirm Hold
# ---------------------------------------------------------------------------


async def confirm_hold(
    booking_id: uuid.UUID,
    payment_reference: str,
    db: AsyncSession,
    redis: Redis,
) -> Booking:
    """
    Step 2 of the Booking Flow.
    Triggered by the Razorpay webhook. Converts HELD to CONFIRMED.
    """
    # 1. Fetch booking
    booking_result = await db.execute(
        select(Booking).where(Booking.id == booking_id)
    )
    booking = booking_result.scalar_one_or_none()
    
    if not booking:
        raise ValueError("Booking not found.")

    if booking.status == "CONFIRMED":
        return booking # Idempotency: webhook hit twice

    if booking.status != "HELD":
        raise ValueError(f"Booking is in invalid state to confirm: {booking.status}")

    # 2. Redis Key Verification (optional safety check)
    lock_key = f"hold:{booking.room_block_id}:{booking.room_type}:{booking.guest_id}"

    # 3. PostgreSQL Layer-2 Final Update
    allotment_result = await db.execute(
        select(RoomBlockAllotment)
        .where(RoomBlockAllotment.id == booking.allotment_id)
        .with_for_update()  # Lock just this row
    )
    allotment = allotment_result.scalar_one()

    # Move from held pool to booked pool
    # We do not subtract from available calculation, we just change the state
    if allotment.held_rooms > 0:
        allotment.held_rooms -= 1
    
    allotment.booked_rooms += 1
    allotment.version += 1

    booking.status = "CONFIRMED"
    booking.payment_reference = payment_reference
    booking.hold_expires_at = None

    # Phase 2D: Wallet Integration (Split Ledger)
    wallet_result = await db.execute(
        select(Wallet).where(Wallet.guest_id == booking.guest_id)
    )
    wallet = wallet_result.scalar_one_or_none()

    if wallet and wallet.balance > 0:
        # Deduct from wallet if possible
        subsidy_amount = min(wallet.balance, booking.total_cost)
        if subsidy_amount > 0:
            await debit_on_booking(wallet.id, booking.id, subsidy_amount, db)
            booking.subsidy_applied = subsidy_amount
            booking.amount_due = booking.total_cost - subsidy_amount
    
    await db.commit()
    await db.refresh(booking)

    # 4. Release Redis lock affirmatively
    await redis.delete(lock_key)

    # Fire off background confirmation email
    send_booking_confirmation_email.delay(str(booking.id))

    # ── Phase 5: Dashboard Emission (AFTER commit — fire-and-forget) ──
    # Fetch the guest name for the emission payload
    guest_result = await db.execute(select(Guest.name).where(Guest.id == booking.guest_id))
    guest_name = guest_result.scalar_one_or_none() or "Guest"

    await emit_booking_confirmed(
        redis=redis,
        event_id=booking.event_id,
        guest_name=guest_name,
        room_type=booking.room_type,
        allotment=allotment,
        subsidy_applied=float(booking.subsidy_applied),
        total_cost=float(booking.total_cost),
        num_nights=booking.num_nights,
    )
    await check_block_thresholds(redis, booking.event_id, allotment)

    # Check budget thresholds if a subsidy was applied
    if booking.subsidy_applied > 0 and wallet:
        total_loaded_q = select(func.sum(WalletTransaction.amount)).join(Wallet).where(
            Wallet.event_id == booking.event_id,
            WalletTransaction.type == "credit",
        )
        total_loaded = (await db.execute(total_loaded_q)).scalar() or 0
        total_spent_q = select(func.sum(WalletTransaction.amount)).join(Wallet).where(
            Wallet.event_id == booking.event_id,
            WalletTransaction.type == "debit",
        )
        total_spent = (await db.execute(total_spent_q)).scalar() or 0
        await check_budget_thresholds(redis, booking.event_id, float(total_loaded), float(total_spent))

    return booking


# ---------------------------------------------------------------------------
# Cancellations & Waitlist Cascade
# ---------------------------------------------------------------------------


async def cancel_booking(
    booking_id: uuid.UUID,
    db: AsyncSession,
    redis: Redis,
) -> Booking:
    """
    Cancel an active reservation and immediately promote the next waitlist person.
    Everything runs in a single transaction — one commit at the end.
    """
    booking_result = await db.execute(
        select(Booking).where(Booking.id == booking_id)
    )
    booking = booking_result.scalar_one_or_none()
 
    if not booking:
        raise ValueError("Booking not found.")
 
    if booking.status == "CANCELLED":
        return booking
 
    # Lock the allotment row and decrement the right counter
    allotment_result = await db.execute(
        select(RoomBlockAllotment)
        .where(RoomBlockAllotment.id == booking.allotment_id)
        .with_for_update()
    )
    allotment = allotment_result.scalar_one()
 
    if booking.status == "CONFIRMED":
        if allotment.booked_rooms > 0:
            allotment.booked_rooms -= 1
    elif booking.status == "HELD":
        if allotment.held_rooms > 0:
            allotment.held_rooms -= 1
        lock_key = f"hold:{booking.room_block_id}:{booking.room_type}:{booking.guest_id}"
        await redis.delete(lock_key)
 
    booking.status = "CANCELLED"
    booking.hold_expires_at = None
    allotment.version += 1
 
    # Phase 2D: Refund the corporate wallet if subsidy was applied
    if booking.subsidy_applied > 0:
        wallet_result = await db.execute(
            select(Wallet).where(Wallet.guest_id == booking.guest_id)
        )
        wallet = wallet_result.scalar_one_or_none()
        if wallet:
            await credit_on_cancellation(wallet.id, booking.id, booking.subsidy_applied, db)
 
    # Promote the next person — NO commit inside promote_next,
    # everything flushes together below.
    await promote_next(booking.room_block_id, booking.room_type, db)
 
    # Single commit — cancellation + promotion are atomic.
    await db.commit()
    await db.refresh(booking)

    # ── Phase 5: Dashboard Emission (AFTER commit — fire-and-forget) ──
    guest_result = await db.execute(select(Guest.name).where(Guest.id == booking.guest_id))
    guest_name = guest_result.scalar_one_or_none() or "Guest"

    await emit_booking_cancelled(
        redis=redis,
        event_id=booking.event_id,
        guest_name=guest_name,
        room_type=booking.room_type,
        allotment=allotment,
        refund_amount=float(booking.subsidy_applied),
    )

    return booking


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


async def get_bookings_for_event(
    event_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    status_filter: str | None = None,
) -> tuple[list[Booking], int]:
    
    query = select(Booking).where(
        Booking.event_id == event_id, Booking.tenant_id == tenant_id
    )
    if status_filter:
        query = query.where(Booking.status == status_filter)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    
    return list(result.scalars().all()), total


# ---------------------------------------------------------------------------
# Public: Fetch guest's own booking via magic-link token (no JWT required)
# ---------------------------------------------------------------------------


async def get_guest_booking_by_token(
    guest_token: uuid.UUID,
    db: AsyncSession,
) -> Booking | None:
    """
    Returns the guest's most recent active booking (HELD or CONFIRMED)
    using only their booking_token. Used by the public microsite to detect
    if the guest already has / had a booking and show the right UI state.
    """
    # 1. Validate the guest token
    guest_result = await db.execute(
        select(Guest).where(
            Guest.booking_token == guest_token,
            Guest.is_active == True,
        )
    )
    guest = guest_result.scalar_one_or_none()
    if not guest:
        return None

    # 2. Find their most recent active booking for this event
    booking_result = await db.execute(
        select(Booking)
        .where(
            Booking.guest_id == guest.id,
            Booking.event_id == guest.event_id,
            Booking.status.in_(["HELD", "CONFIRMED"]),
        )
        .order_by(Booking.created_at.desc())
        .limit(1)
    )
    return booking_result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Public: Cancel guest's own booking via magic-link token (no JWT required)
# ---------------------------------------------------------------------------


async def cancel_booking_by_token(
    guest_token: uuid.UUID,
    db: AsyncSession,
    redis: Redis,
) -> Booking:
    """
    Allows a guest to cancel their own HELD or CONFIRMED booking using only
    their magic-link token. Triggers full cascade:
    - Returns room to inventory
    - Refunds corporate wallet subsidy (if any was applied)
    - Promotes the next person on the waitlist
    No planner auth required.
    """
    # 1. Find the guest
    guest_result = await db.execute(
        select(Guest).where(
            Guest.booking_token == guest_token,
            Guest.is_active == True,
        )
    )
    guest = guest_result.scalar_one_or_none()
    if not guest:
        raise ValueError("Invalid or inactive guest token.")

    # 2. Find their active booking
    booking_result = await db.execute(
        select(Booking)
        .where(
            Booking.guest_id == guest.id,
            Booking.event_id == guest.event_id,
            Booking.status.in_(["HELD", "CONFIRMED"]),
        )
        .order_by(Booking.created_at.desc())
        .limit(1)
    )
    booking = booking_result.scalar_one_or_none()
    if not booking:
        raise ValueError("No active booking found to cancel.")

    # 3. Delegate to existing cancel_booking (handles inventory + wallet + waitlist cascade)
    return await cancel_booking(booking_id=booking.id, db=db, redis=redis)

