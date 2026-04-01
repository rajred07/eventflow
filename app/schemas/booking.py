"""
Booking Schemas — models for the transactional reservation process.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------


class BookingHoldRequest(BaseModel):
    """Payload to attempt a 15-minute room hold (Step 1)."""

    guest_token: uuid.UUID
    room_block_id: uuid.UUID
    room_type: str = Field(..., max_length=100)


class BookingConfirmRequest(BaseModel):
    """
    Payload when the Razorpay webhook returns a successful payment (Step 2).
    In a real app, you would also pass Razorpay signatures to verify,
    but here we expect the proxy/webhook handler to just pass the ref.
    """

    # Razorpay payment ID or internal reference
    payment_reference: str
    
    # Actually, the webhook would probably provide its own ID, but the router
    # maps it to the internal `hold_id`. For our REST API, we'll put `hold_id`
    # in the path `PUT /bookings/{hold_id}/confirm`.


# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------


class BookingResponse(BaseModel):
    """Data returned to guest or planner."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    event_id: uuid.UUID
    guest_id: uuid.UUID
    room_block_id: uuid.UUID
    allotment_id: uuid.UUID
    room_type: str
    check_in_date: date
    check_out_date: date
    num_nights: int

    room_rate_per_night: Decimal
    total_cost: Decimal
    subsidy_applied: Decimal
    amount_due: Decimal

    status: str
    hold_expires_at: datetime | None
    payment_reference: str | None
    special_requests: str | None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BookingListResponse(BaseModel):
    """Paginated response for planner dashboard."""
    items: list[BookingResponse]
    total: int
    page: int
    page_size: int
