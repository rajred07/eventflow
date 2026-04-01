"""
Waitlist Model — tracks guests waiting for a specific room type.

Instead of storing a hard-coded `position` integer (which would require
expensive cascading UPDATE statements every time someone is promoted),
we use the `added_at` timestamp.

"Next in line" is simply the oldest record where status = "waiting".
A guest's position is computed dynamically:
    COUNT(*) WHERE status='waiting' AND added_at < this_guest.added_at
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Waitlist(Base):
    __tablename__ = "waitlist"

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

    guest_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("guests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    room_block_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("room_blocks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    room_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Status transitions:
    # "waiting"   -> Guest is in line.
    # "offered"   -> Room opened up, email sent, waiting for guest to accept.
    # "converted" -> Guest accepted and booked the room.
    # "expired"   -> Guest ignored the offer for > 24 hours.
    # "cancelled" -> Guest manually left the waitlist.
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="waiting", index=True
    )

    # When the next-in-line guest is promoted, they get 24 hours to book
    offer_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    tenant = relationship("Tenant")
    event = relationship("Event")
    guest = relationship("Guest")
    room_block = relationship("RoomBlock")

    def __repr__(self) -> str:
        return f"<Waitlist {self.guest_id} - {self.room_type} ({self.status})>"
