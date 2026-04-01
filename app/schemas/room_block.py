"""
Room Block Schemas — request/response Pydantic models for inventory management.
"""

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------


class AllotmentCreate(BaseModel):
    """Details for a single room type allotment when creating a block."""

    room_type: str = Field(..., max_length=100, examples=["standard"])
    total_rooms: int = Field(..., ge=1, examples=[50])
    negotiated_rate: Decimal = Field(..., ge=0, decimal_places=2, examples=[8500.00])

    @field_validator("room_type")
    @classmethod
    def format_room_type(cls, v: str) -> str:
        return v.strip().lower()


class RoomBlockCreate(BaseModel):
    """Payload to create a Room Block and its allotments."""

    venue_id: uuid.UUID
    check_in_date: date = Field(..., examples=["2026-03-15"])
    check_out_date: date = Field(..., examples=["2026-03-18"])
    hold_deadline: date = Field(
        ...,
        examples=["2026-02-15"],
        description="Date when unclaimed rooms are released back to the hotel",
    )
    notes: str | None = None

    allotments: list[AllotmentCreate] = Field(
        ...,
        min_length=1,
        description="List of room types and their quantities/prices",
    )

    @field_validator("check_out_date")
    @classmethod
    def validate_dates(cls, v: date, info) -> date:
        if "check_in_date" in info.data and v <= info.data["check_in_date"]:
            raise ValueError("check_out_date must be after check_in_date")
        return v


class RoomBlockUpdate(BaseModel):
    """Update general Room Block details."""

    status: str | None = Field(default=None, pattern="^(pending|confirmed|cancelled|released)$")
    check_in_date: date | None = None
    check_out_date: date | None = None
    hold_deadline: date | None = None
    notes: str | None = None


class AllotmentUpdate(BaseModel):
    """Update a specific room type inventory/price."""

    total_rooms: int | None = Field(default=None, ge=1)
    negotiated_rate: Decimal | None = Field(default=None, ge=0, decimal_places=2)


# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------


class AllotmentResponse(BaseModel):
    id: uuid.UUID
    room_block_id: uuid.UUID
    room_type: str
    total_rooms: int
    booked_rooms: int
    held_rooms: int
    negotiated_rate: Decimal
    version: int

    # Computed field for convenience
    @property
    def available_rooms(self) -> int:
        return self.total_rooms - (self.booked_rooms + self.held_rooms)

    model_config = {"from_attributes": True}


class RoomBlockResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    event_id: uuid.UUID
    venue_id: uuid.UUID
    status: str
    check_in_date: date
    check_out_date: date
    hold_deadline: date
    notes: str | None
    
    # Needs lazy="selectin" on the relationship
    allotments: list[AllotmentResponse] = []

    model_config = {"from_attributes": True}


class RoomBlockListResponse(BaseModel):
    blocks: list[RoomBlockResponse]
    total: int
