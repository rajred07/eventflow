"""
Tenant Model — represents an organization using the platform.

A tenant is a company, wedding planner, or agency that has their
own isolated space on Eventflow. All data (events, guests, bookings)
belongs to a tenant and is invisible to other tenants.

Examples:
- "Acme Corp" (corporate tenant managing MICE events)
- "Dream Weddings by Priya" (wedding planner managing destination weddings)
"""

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Tenant(Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    slug: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )

    # "corporate" | "wedding_planner" | "agency"
    type: Mapped[str] = mapped_column(String(50), nullable=False, default="corporate")

    # Flexible settings: branding, defaults, feature flags
    # Example: {"branding": {"primary_color": "#1a1a2e"}, "default_currency": "INR"}
    settings: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(default=True)

    # Relationships
    users = relationship("User", back_populates="tenant", lazy="selectin")
    events = relationship("Event", back_populates="tenant", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Tenant {self.name} ({self.slug})>"
