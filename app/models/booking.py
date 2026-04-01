"""
Booking Model — the core transaction.

This tracks the reservation from the 15-minute HELD stage
through CONFIRMED, CANCELLED, and CHECKED_IN.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Booking(Base):
    __tablename__ = "bookings"

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

    allotment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("room_block_allotments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        # Restrict makes sure we don't accidentally delete an allotment
        # if there are active bookings against it.
    )

    room_type: Mapped[str] = mapped_column(String(100), nullable=False)
    
    check_in_date: Mapped[date] = mapped_column(Date, nullable=False)
    check_out_date: Mapped[date] = mapped_column(Date, nullable=False)
    num_nights: Mapped[int] = mapped_column(Integer, nullable=False)

    # Price breakdown (recorded at time of booking to freeze rates)
    room_rate_per_night: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    total_cost: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    subsidy_applied: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0.00)
    amount_due: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    # Status: HELD | CONFIRMED | EXPIRED | CANCELLED | CHECKED_IN | CHECKED_OUT
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="HELD", index=True)
    
    # Track the 15-minute layer-1 hold expiry. Celery watches this.
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    payment_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    
    special_requests: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    extra_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # A guest should generally only book one room for themselves per event,
    # unless they are allowed to book for +1s. For simplicity, we restrict
    # them to 1 active room booking per event here.
    __table_args__ = (
        UniqueConstraint(
            "guest_id", "event_id", name="uq_guest_event_booking"
        ),
    )

    # Relationships
    tenant = relationship("Tenant", backref="bookings")
    event = relationship("Event", backref="bookings")
    guest = relationship("Guest", backref="booking")
    room_block = relationship("RoomBlock", backref="bookings")
    allotment = relationship("RoomBlockAllotment", backref="bookings")

    def __repr__(self) -> str:
        return f"<Booking {self.id} for Guest {self.guest_id} ({self.status})>"
