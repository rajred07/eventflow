"""
Venue Schemas — request/response models for venue endpoints.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class VenueCreate(BaseModel):
    """Payload to create a new venue."""
    name: str
    city: str
    state: str
    total_rooms: int = 100
    contact_email: str | None = None


class VenueResponse(BaseModel):
    """Full venue data returned in API responses."""

    id: uuid.UUID
    name: str
    city: str
    state: str
    address: str | None
    latitude: float | None
    longitude: float | None
    total_rooms: int
    max_event_capacity: int | None
    star_rating: float | None
    user_rating: float | None
    description: str | None
    amenities: list | None
    pricing_tiers: dict | None
    images: list | None
    contact_email: str | None
    contact_phone: str | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class VenueListResponse(BaseModel):
    """Paginated list of venues with optional filters."""

    venues: list[VenueResponse]
    total: int
    page: int
    page_size: int


class VenueFilterParams(BaseModel):
    """Query parameters for filtering venues."""

    city: str | None = None
    min_rooms: int | None = Field(default=None, ge=1)
    max_price: float | None = Field(default=None, ge=0)
    min_rating: float | None = Field(default=None, ge=0, le=5)
    amenities: list[str] | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
