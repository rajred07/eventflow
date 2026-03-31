"""
Event Schemas — request/response models for event endpoints.
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class EventCreate(BaseModel):
    """Create a new event."""

    name: str = Field(
        ..., min_length=2, max_length=255, examples=["Annual Corporate Offsite 2026"]
    )
    type: str = Field(
        default="mice",
        pattern="^(mice|wedding|offsite|conference)$",
        examples=["mice"],
    )
    description: str | None = Field(
        default=None, examples=["3-day team offsite in Goa with sessions and activities"]
    )
    destination: str | None = Field(default=None, examples=["Goa"])
    start_date: date = Field(..., examples=["2026-03-15"])
    end_date: date = Field(..., examples=["2026-03-18"])
    expected_guests: int = Field(default=0, ge=0, examples=[200])
    category_rules: dict | None = Field(
        default=None,
        examples=[
            {
                "employee": {
                    "allowed_room_types": ["standard", "deluxe"],
                    "subsidy_per_night": 8000,
                },
                "vip": {
                    "allowed_room_types": ["deluxe", "suite"],
                    "subsidy_per_night": 15000,
                },
            }
        ],
    )
    extra_data: dict | None = None


class EventUpdate(BaseModel):
    """Update an event (all fields optional)."""

    name: str | None = Field(default=None, min_length=2, max_length=255)
    type: str | None = Field(default=None, pattern="^(mice|wedding|offsite|conference)$")
    status: str | None = Field(
        default=None, pattern="^(draft|active|completed|cancelled)$"
    )
    description: str | None = None
    destination: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    expected_guests: int | None = Field(default=None, ge=0)
    category_rules: dict | None = None
    extra_data: dict | None = None


class EventResponse(BaseModel):
    """Full event data returned in API responses."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    created_by: uuid.UUID | None
    name: str
    type: str
    status: str
    description: str | None
    destination: str | None
    start_date: date
    end_date: date
    expected_guests: int
    category_rules: dict | None
    extra_data: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EventListResponse(BaseModel):
    """Paginated list of events."""

    events: list[EventResponse]
    total: int
    page: int
    page_size: int
