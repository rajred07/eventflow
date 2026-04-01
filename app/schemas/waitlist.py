"""
Waitlist Schemas — request/response Pydantic models for the waitlist system.

Waitlist positions are computed at query time, so they are only present
in the response models, not the create/update models.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------


class WaitlistCreate(BaseModel):
    """Payload to add a guest to the waitlist."""

    # Note: guest_id comes from the auth token in the public portal,
    # or is provided by the planner explicitly.
    guest_id: uuid.UUID
    room_block_id: uuid.UUID
    room_type: str = Field(..., max_length=100, examples=["standard"])

    @field_validator("room_type")
    @classmethod
    def format_room_type(cls, v: str) -> str:
        return v.strip().lower()


class WaitlistActionRequest(BaseModel):
    """Payload when a planner manually changes waitlist status."""

    status: str = Field(..., pattern="^(offered|expired|cancelled)$")


# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------


class WaitlistResponse(BaseModel):
    """Data returned to the planner or guest."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    event_id: uuid.UUID
    guest_id: uuid.UUID
    room_block_id: uuid.UUID
    room_type: str
    status: str
    offer_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime

    # POSITION IS COMPUTED AT QUERY TIME!
    # How many people are ahead of this guest for this specific room_type.
    # 1 = next in line.
    # If the guest is not status='waiting', position is None or 0.
    position: int | None = None

    model_config = {"from_attributes": True}


class WaitlistListResponse(BaseModel):
    """Paginated list of waitlist entries."""

    items: list[WaitlistResponse]
    total: int
    page: int
    page_size: int
