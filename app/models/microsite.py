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
    theme_color = Column(String(50), default="#0f172a") # Default Slate-900
    hero_image_url = Column(String(1024), nullable=True)
    welcome_message = Column(Text, nullable=True)
    
    is_published = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
