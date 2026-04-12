import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base

class Microsite(Base):
    __tablename__ = "microsites"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id = Column(UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, unique=True)
    
    slug = Column(String(255), unique=True, nullable=False, index=True)
    theme_color = Column(String(50), default="#c29b40")
    hero_image_url = Column(String(1024), nullable=True)
    tagline = Column(String(255), nullable=True)  # e.g. "THE CURATED SANCTUARY"
    welcome_message = Column(Text, nullable=True)
    support_email = Column(String(255), nullable=True)
    support_phone = Column(String(50), nullable=True)
    
    is_published = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
