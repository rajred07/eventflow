"""
Guest Schemas — request/response Pydantic models for guest endpoints.

Three layers:
  - GuestCreate / GuestBulkCreate  → what the planner POSTs
  - GuestUpdate                    → what the planner PUTs (all optional)
  - GuestResponse / GuestListResponse → what the API returns
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------


class GuestCreate(BaseModel):
    """Create a single guest for an event."""

    name: str = Field(
        ...,
        min_length=2,
        max_length=255,
        examples=["Rahul Sharma"],
    )
    email: EmailStr | None = Field(
        default=None,
        examples=["rahul.sharma@acmecorp.com"],
        description="Optional at creation — can be added later via update.",
    )
    phone: str | None = Field(
        default=None,
        max_length=50,
        examples=["+91-98765-43210"],
    )
    category: str = Field(
        default="delegate",
        max_length=100,
        examples=["employee"],
        description=(
            "Category controls which room types and subsidy this guest gets. "
            "Must match a key in the event's category_rules. "
            "Examples: employee, vip, family, delegate, speaker"
        ),
    )
    dietary_requirements: dict | None = Field(
        default=None,
        examples=[{"vegetarian": True, "nut_allergy": True}],
    )
    extra_data: dict | None = Field(
        default=None,
        examples=[{"department": "Engineering", "employee_id": "EMP-1042"}],
    )

    @field_validator("category")
    @classmethod
    def category_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("category cannot be blank")
        return v.strip().lower()


class GuestBulkCreateItem(BaseModel):
    """A single guest entry inside a bulk import payload."""

    name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    category: str = Field(default="delegate", max_length=100)
    dietary_requirements: dict | None = None
    extra_data: dict | None = None

    @field_validator("category")
    @classmethod
    def category_lowercase(cls, v: str) -> str:
        return v.strip().lower()


class GuestBulkCreate(BaseModel):
    """Bulk import: up to 500 guests in a single request."""

    guests: list[GuestBulkCreateItem] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="List of guests to import. Max 500 per request.",
    )


class GuestUpdate(BaseModel):
    """Update a guest — all fields optional."""

    name: str | None = Field(default=None, min_length=2, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=100)
    dietary_requirements: dict | None = None
    extra_data: dict | None = None

    @field_validator("category")
    @classmethod
    def category_lowercase(cls, v: str | None) -> str | None:
        if v is not None:
            return v.strip().lower()
        return v


# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------


class GuestResponse(BaseModel):
    """Full guest data returned in API responses."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    event_id: uuid.UUID
    name: str
    email: str | None
    phone: str | None
    category: str
    booking_token: uuid.UUID
    is_active: bool
    dietary_requirements: dict | None
    extra_data: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GuestListResponse(BaseModel):
    """Paginated list of guests."""

    guests: list[GuestResponse]
    total: int
    page: int
    page_size: int


class GuestBulkCreateResponse(BaseModel):
    """Result of a bulk import operation."""

    created: int
    skipped: int
    errors: list[str]
    guests: list[GuestResponse]
