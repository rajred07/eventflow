"""
Venue Model — a hotel or resort that can host events.

Venues are global (not tenant-specific) — they exist independently
and any tenant can search for and request room blocks from them.

The amenities JSONB and pricing_tiers JSONB allow flexible,
schema-less data that varies wildly between venues without
needing separate tables for every amenity type.

Vector embedding and tsvector columns will be added in Phase 3
for NLP-powered venue search.
"""

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Venue(Base):
    __tablename__ = "venues"

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Location
    city: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Capacity
    total_rooms: Mapped[int] = mapped_column(Integer, nullable=False)
    max_event_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Star rating (1-5)
    star_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    user_rating: Mapped[float | None] = mapped_column(Float, nullable=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Amenities as flexible JSON
    # Example: ["conference_hall", "pool", "spa", "airport_shuttle", "wifi"]
    amenities: Mapped[list | None] = mapped_column(JSONB, default=list)

    # Room types and base pricing
    # Example: {"standard": 6000, "deluxe": 10000, "suite": 18000}
    pricing_tiers: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # Image URLs
    images: Mapped[list | None] = mapped_column(JSONB, default=list)

    # Contact
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    is_active: Mapped[bool] = mapped_column(default=True)

    # Phase 3 additions (commented out until pgvector is set up):
    # embedding: Mapped[list] = mapped_column(Vector(768))  # pgvector
    # search_vector: Mapped[str] = mapped_column(TSVector)  # Full-text search
    
    # Relationships
    room_blocks = relationship("RoomBlock", back_populates="venue", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Venue {self.name} ({self.city})>"
