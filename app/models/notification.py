import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, Integer
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base

class NotificationLog(Base):
    """
    Records every single email transaction in the system.
    Provides complete auditability for failures and tracking.
    """
    __tablename__ = "notification_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    guest_id = Column(UUID(as_uuid=True), ForeignKey("guests.id", ondelete="CASCADE"), nullable=True, index=True)

    # e.g., "invitation", "booking_confirmation", "waitlist_offer", "reminder_7d"
    type = Column(String(50), nullable=False, index=True)
    
    # "pending", "success", "failed"
    status = Column(String(50), nullable=False, default="pending", index=True)
    
    # Provider data
    recipient_email = Column(String(255), nullable=False)
    provider_message_id = Column(String(255), nullable=True) # Resend Message ID
    
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)

    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
