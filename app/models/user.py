"""
User Model — a person who belongs to a tenant.

Users have roles that determine what they can do:
- admin: Full access (manage everything for this tenant)
- planner: Can create events, manage guests, blocks
- viewer: Read-only access to dashboards
- hotel_admin: Hotel-side user who manages allotments
"""

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # "admin" | "planner" | "viewer" | "hotel_admin"
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="planner")

    is_active: Mapped[bool] = mapped_column(default=True)

    # User preferences: notification settings, UI preferences, etc.
    preferences: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Relationships
    tenant = relationship("Tenant", back_populates="users")

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role})>"
