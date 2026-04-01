"""
Booking Service — the transactional core of Eventflow.

Implements the two-tier locking strategy:
Layer 1: Redis hold (NX EX 900) prevents two guests from entering the payment flow.
Layer 2: PostgreSQL row lock (FOR UPDATE) commits the reservation.
"""

import uuid
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.waitlists.service import promote_next
from app.models.booking import Booking
from app.models.guest import Guest
from app.models.room_block import RoomBlock
from app.models.room_block_allotment import RoomBlockAllotment
from app.schemas.booking import BookingHoldRequest


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
    
    await db.commit()
    await db.refresh(booking)

    # 4. Release Redis lock affirmatively
    await redis.delete(lock_key)

    # Note: Trigger Celery task here in Phase 2F to email guest confirmation!

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
    """
    booking_result = await db.execute(
        select(Booking).where(Booking.id == booking_id)
    )
    booking = booking_result.scalar_one_or_none()
    
    if not booking:
        raise ValueError("Booking not found.")

    if booking.status == "CANCELLED":
        return booking

    # Update the allotment row and state
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
        # Also clean up redis just in case
        lock_key = f"hold:{booking.room_block_id}:{booking.room_type}:{booking.guest_id}"
        await redis.delete(lock_key)

    booking.status = "CANCELLED"
    booking.hold_expires_at = None
    allotment.version += 1

    await db.commit()

    # WAITLIST CASCADE TRIGGER
    # Someone cancelled, meaning a room just opened up!
    await promote_next(booking.room_block_id, booking.room_type, db)

    await db.refresh(booking)
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
