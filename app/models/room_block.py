"""
Room Block Model — the contract between an Event and a Venue.

A RoomBlock reserves rooms at a specific venue for specific dates.
In Phase 2, planners create these directly in "confirmed" status.
(In Phase 5, this will be the basis for the negotiation workflow).
"""

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RoomBlock(Base):
    __tablename__ = "room_blocks"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    venue_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("venues.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Status: "pending", "confirmed", "cancelled", "released"
    # Phase 2: created as "confirmed" directly.
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="confirmed"
    )

    check_in_date: Mapped[date] = mapped_column(Date, nullable=False)
    check_out_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Automatically release unclaimed rooms back to the hotel after this date
    hold_deadline: Mapped[date] = mapped_column(Date, nullable=False)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    tenant = relationship("Tenant")
    event = relationship("Event", back_populates="room_blocks")
    venue = relationship("Venue", back_populates="room_blocks")
    allotments = relationship(
        "RoomBlockAllotment",
        back_populates="room_block",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<RoomBlock {self.id} (Event: {self.event_id}, Status: {self.status})>"
