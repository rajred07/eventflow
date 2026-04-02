"""
Guest Model — a person invited to an event.

Guests are the core entity that binds everything together in Phase 2+.
Each guest belongs to a specific event under a tenant and has:

  - category: determines which rooms they can book and how much
    subsidy they receive (pulled from event.category_rules)

  - booking_token: a secret UUID used as a magic-link for self-service
    booking via the microsite. The guest never logs in — this token
    IS their identity on the public booking flow.

  - dietary_requirements: free-form JSONB for hotel kitchen planning

  - extra_data: any other info the planner wants to store
    (e.g., travel mode, companion names, t-shirt size for offsites)

Design note:
  Email is nullable because large corporate events often add guests
  by name + employee ID first, then backfill email later via bulk
  import. We don't want to block guest creation on missing email.
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Guest(Base):
    __tablename__ = "guests"

    # Tenant scoping — RLS uses this
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Which event this guest belongs to
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Nullable — not all guests have email at time of import
    email: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )

    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Category controls room access and subsidy (see event.category_rules)
    # Examples: "employee" | "vip" | "family" | "delegate" | "speaker"
    category: Mapped[str] = mapped_column(
        String(100), nullable=False, default="delegate", index=True
    )

    # Magic-link token for microsite self-booking — unique per guest
    # This is the guest's identity on public routes, never their password
    booking_token: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        default=uuid.uuid4,
        unique=True,
        index=True,
    )

    # Soft-delete instead of hard delete — preserves booking history
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Flexible JSONB fields
    dietary_requirements: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    extra_data: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Prevent duplicate email within the same event
    # (same person cannot be invited twice to the same event)
    __table_args__ = (
        UniqueConstraint("event_id", "email", name="uq_guest_event_email"),
    )

    # Relationships
    tenant = relationship("Tenant")
    event = relationship("Event", back_populates="guests")
    wallet = relationship("Wallet", back_populates="guest", uselist=False)

    def __repr__(self) -> str:
        return f"<Guest {self.name} ({self.category}) event={self.event_id}>"
