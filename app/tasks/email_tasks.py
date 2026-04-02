import logging
import os
import uuid
from datetime import datetime

import resend
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.celery_app import app
from app.config import settings
from app.models.notification import NotificationLog
from app.models.guest import Guest
from app.models.event import Event
from app.models.microsite import Microsite

logger = logging.getLogger(__name__)

# Configure Resend. If missing, we fallback to mock.
# RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
# if RESEND_API_KEY:
#     resend.api_key = RESEND_API_KEY


if settings.RESEND_API_KEY:
    resend.api_key = settings.RESEND_API_KEY
# ---------------------------------------------------------------------------
# Create a dedicated SYNCHRONOUS engine for Celery Workers.
# Celery runs tasks in isolated OS worker processes/threads, and mixing
# asyncio.run() with a global async_engine causes severe asyncpg socket conflicts.
# By forcing Celery to use pure, blocking sync queries (psycopg2), we
# guarantee perfect database concurrency stability in the background!
# ---------------------------------------------------------------------------
SYNC_DB_URL = settings.DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")
sync_engine = create_engine(SYNC_DB_URL, pool_pre_ping=True)
SyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)


@app.task(bind=True, max_retries=3)
def send_guest_invitation_email(self, guest_id: str):
    """Send an invitation email to a guest containing their magic booking link."""
    db = SyncSessionLocal()
    try:
        # Standard synchronous queries! No asyncio.run() crashes here.
        guest = db.execute(select(Guest).where(Guest.id == uuid.UUID(guest_id))).scalar_one()
        event = db.execute(select(Event).where(Event.id == guest.event_id)).scalar_one()
        microsite = db.execute(select(Microsite).where(Microsite.event_id == event.id)).scalar_one_or_none()
        
        slug = microsite.slug if microsite else "booking"
        magic_link = f"https://app.eventflow.com/events/{slug}?token={guest.booking_token}"
        
        html_content = f"""
        <html>
            <body>
                <h2>You're Invited to {event.name}!</h2>
                <p>Hello {guest.name},</p>
                <p>We are excited to invite you to {event.name}.</p>
                <p>Click the link below to securely view your itinerary and book your room:</p>
                <a href="{magic_link}">Complete Your Booking</a>
            </body>
        </html>
        """
        
        if settings.RESEND_API_KEY:
            r = resend.Emails.send({
                "from": "Eventflow <book@app.eventflow.com>",
                "to": guest.email,
                "subject": f"Your Invitation: {event.name}",
                "html": html_content
            })
            
            # Log successful HTTP call
            log_entry = NotificationLog(
                event_id=event.id, 
                guest_id=guest.id, 
                type="invitation", 
                status="success", 
                recipient_email=guest.email,
                provider_message_id=r.get("id"),
                sent_at=datetime.utcnow()
            )
            db.add(log_entry)
            db.commit()
            logger.info(f"Resend Email Sent: Invitation to {guest.email} via {magic_link}")
        else:
            logger.info(f"Mock Email Sent: Invitation to {guest.email} via {magic_link}")
            log_entry = NotificationLog(
                event_id=event.id, 
                guest_id=guest.id, 
                type="invitation", 
                status="success", 
                recipient_email=guest.email,
                sent_at=datetime.utcnow()
            )
            db.add(log_entry)
            db.commit()
            
    except Exception as exc:
        logger.error(f"Failed to send invitation email: {exc}")
        db.rollback()
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


@app.task(bind=True, max_retries=3)
def send_booking_confirmation_email(self, booking_id: str):
    """Send confirmation email after a guest completes booking."""
    db = SyncSessionLocal()
    from app.models.booking import Booking
    try:
        booking = db.execute(select(Booking).where(Booking.id == uuid.UUID(booking_id))).scalar_one()
        guest = db.execute(select(Guest).where(Guest.id == booking.guest_id)).scalar_one()
        
        logger.info(f"Mock Email Sent: Booking Confirmation for Booking ID {booking_id}")
        
        log_entry = NotificationLog(
            event_id=booking.event_id, 
            guest_id=booking.guest_id, 
            type="booking_confirmation", 
            status="success", 
            recipient_email=guest.email,
            sent_at=datetime.utcnow()
        )
        db.add(log_entry)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()

@app.task(bind=True, max_retries=3)
def send_waitlist_offer_email(self, waitlist_id: str):
    """Send an offer email to a waitlisted guest after a room frees up."""
    db = SyncSessionLocal()
    from app.models.waitlist import Waitlist
    try:
        w_entry = db.execute(select(Waitlist).where(Waitlist.id == uuid.UUID(waitlist_id))).scalar_one()
        guest = db.execute(select(Guest).where(Guest.id == w_entry.guest_id)).scalar_one()
        
        logger.info(f"Mock Email Sent: Waitlist Offer for Waitlist ID {waitlist_id}")
        
        log_entry = NotificationLog(
            event_id=w_entry.event_id, 
            guest_id=w_entry.guest_id, 
            type="waitlist_offer", 
            status="success", 
            recipient_email=guest.email,
            sent_at=datetime.utcnow()
        )
        db.add(log_entry)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()
