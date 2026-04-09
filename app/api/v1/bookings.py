"""
Booking Routes — Transactional endpoints for managing room inventory.

POST   /api/v1/public/hold             → Guest creates a 15-minute Layer-1 lock
POST   /api/v1/webhooks/razorpay       → Confirm lock via payment success
GET    /api/v1/events/{id}/bookings    → Planner list all bookings
DELETE /api/v1/bookings/{id}           → Cancel booking & trigger waitlist
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.rbac import require_role
from app.core.bookings.service import (
    cancel_booking,
    cancel_booking_by_token,
    confirm_hold,
    create_hold,
    get_bookings_for_event,
    get_guest_booking_by_token,
)
from app.core.redis import get_redis
from app.db.session import get_db
from app.models.user import User
from app.schemas.booking import (
    BookingConfirmRequest,
    BookingHoldRequest,
    BookingListResponse,
    BookingResponse,
)


# Public route — guests booking from the microsite
public_booking_router = APIRouter(prefix="/public", tags=["Public Bookings"])

# Admin route — planners managing bookings
booking_router = APIRouter(prefix="/bookings", tags=["Bookings"])
event_booking_router = APIRouter(prefix="/events/{event_id}/bookings", tags=["Bookings"])


@public_booking_router.post(
    "/hold",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a 15-minute room hold",
)
async def hold_room_route(
    data: BookingHoldRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """
    Step 1 of the booking flow. Uses the guest_token instead of JWT auth.
    Attempts to secure a 15-minute Redis lock and returns a HELD booking object.
    FRONTEND: Display the `hold_expires_at` countdown timer!
    """
    try:
        booking = await create_hold(data=data, db=db, redis=redis)
        return booking
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")


@public_booking_router.get(
    "/my-booking",
    response_model=BookingResponse | None,
    summary="Get current guest booking via magic-link token (Zero Auth)",
)
async def get_my_booking_route(
    token: uuid.UUID = Query(..., description="Guest Booking Token"),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the guest's most recent HELD or CONFIRMED booking using their
    magic-link token. Returns null (204) if no active booking exists.
    """
    booking = await get_guest_booking_by_token(guest_token=token, db=db)
    return booking


@public_booking_router.post(
    "/cancel",
    response_model=BookingResponse,
    summary="Guest cancels their own booking via magic-link token (Zero Auth)",
)
async def public_cancel_booking_route(
    token: uuid.UUID = Query(..., description="Guest Booking Token"),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """
    Allows a guest to cancel their own HELD or CONFIRMED booking using only
    their magic-link token. No planner JWT required.
    Triggers full cascade: inventory returns, wallet refund, waitlist promotion.
    """
    try:
        booking = await cancel_booking_by_token(guest_token=token, db=db, redis=redis)
        return booking
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@public_booking_router.post(
    "/webhooks/razorpay/{booking_id}/confirm",
    response_model=BookingResponse,
    summary="Confirm a held room (Webhook simulation)",
)
async def confirm_booking_route(
    booking_id: uuid.UUID,
    data: BookingConfirmRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """
    Step 2 of the booking flow. Usually called backend-to-backend by Razorpay.
    For this API, simulating it by passing the booking ID and payment reference.
    Converts HELD to CONFIRMED.
    """
    try:
        booking = await confirm_hold(
            booking_id=booking_id,
            payment_reference=data.payment_reference,
            db=db,
            redis=redis,
        )
        return booking
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@event_booking_router.get(
    "",
    response_model=BookingListResponse,
    summary="List bookings for an event",
)
async def list_bookings_route(
    event_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    current_user: User = Depends(require_role(["admin", "planner", "viewer"])),
    db: AsyncSession = Depends(get_db),
):
    """Get all bookings (HELD, CONFIRMED, CANCELLED) for an event."""
    bookings, total = await get_bookings_for_event(
        event_id=event_id,
        tenant_id=current_user.tenant_id,
        db=db,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
    )
    return BookingListResponse(
        items=[BookingResponse.model_validate(b) for b in bookings],
        total=total,
        page=page,
        page_size=page_size,
    )


@booking_router.delete(
    "/{booking_id}",
    response_model=BookingResponse,
    summary="Cancel booking & trigger waitlist",
)
async def cancel_booking_route(
    booking_id: uuid.UUID,
    current_user: User = Depends(require_role(["admin", "planner"])),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """
    Cancel a booking. This automatically triggers `promote_next` 
    in the background to offer the newly available room to the 
    first person on the waitlist.
    """
    try:
        booking = await cancel_booking(
            booking_id=booking_id,
            db=db,
            redis=redis,
        )
        return booking
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
