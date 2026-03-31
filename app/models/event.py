"""
Event Model — a MICE event or destination wedding.

An event is the central entity that everything else connects to:
events have room blocks, guests, bookings, microsites, and wallets.

The category_rules JSONB field is key — it defines per-category
pricing and room type restrictions. When a guest opens the booking
page, the system checks their category against these rules and
only shows allowed options.

Example category_rules:
{
    "employee": {
        "allowed_room_types": ["standard", "deluxe"],
        "subsidy_per_night": 8000
    },
    "vip": {
        "allowed_room_types": ["deluxe", "suite"],
        "subsidy_per_night": 15000
    },
    "family": {
        "allowed_room_types": ["standard", "deluxe", "suite"],
        "subsidy_per_night": 0
    }
}
"""

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Event(Base):
    __tablename__ = "events"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # "mice" | "wedding" | "offsite" | "conference"
    type: Mapped[str] = mapped_column(String(50), nullable=False, default="mice")

    # "draft" | "active" | "completed" | "cancelled"
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    destination: Mapped[str | None] = mapped_column(String(255), nullable=True)

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    expected_guests: Mapped[int] = mapped_column(Integer, default=0)

    # Per-category pricing and room type rules (see docstring above)
    category_rules: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Flexible extra data: agenda, special instructions, etc.
    # Note: 'metadata' is reserved by SQLAlchemy, so we use 'extra_data'
    extra_data: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Relationships
    tenant = relationship("Tenant", back_populates="events")
    creator = relationship("User", foreign_keys=[created_by])

    def __repr__(self) -> str:
        return f"<Event {self.name} ({self.type}, {self.status})>"
