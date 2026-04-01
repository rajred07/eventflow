"""
Room Block Allotment Model — stores inventory for a single room type.

Architectural decision:
By keeping allotments in separate rows per room type (vs a single JSONB
blob on `room_block`), we avoid cross-type database locking contention.
Guest A booking a "standard" room only locks the standard row.
Guest B booking a "deluxe" room is not blocked at all.
"""

import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RoomBlockAllotment(Base):
    __tablename__ = "room_block_allotments"

    room_block_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("room_blocks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    room_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Inventory fields
    total_rooms: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Bookings that have completed payment/confirmation
    booked_rooms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    # Bookings currently in the 15-minute Redis hold window.
    # Total assigned = booked_rooms + held_rooms
    held_rooms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Cost per night
    negotiated_rate: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )

    # Used for optimistic locking (secondary concurrency safeguard)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}

    # Don't allow duplicates for the same room block + room type
    __table_args__ = (
        UniqueConstraint(
            "room_block_id", "room_type", name="uq_allotment_block_type"
        ),
    )

    # Relationships
    room_block = relationship("RoomBlock", back_populates="allotments")

    def __repr__(self) -> str:
        return (
            f"<RoomBlockAllotment {self.room_type} - "
            f"Total: {self.total_rooms}, Booked: {self.booked_rooms}, "
            f"Held: {self.held_rooms}>"
        )
