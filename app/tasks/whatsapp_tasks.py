"""
Eventflow WhatsApp Tasks — Celery background jobs that send WhatsApp messages via Twilio.

Architecture:
    Mirrors the email_tasks.py structure exactly. Each task corresponds to an
    email task counterpart:

        Email Task                          WhatsApp Task
        ──────────────────────────          ──────────────────────────────
        send_guest_invitation_email     →   send_whatsapp_invitation
        send_booking_confirmation_email →   send_whatsapp_booking_confirmation
        send_waitlist_offer_email       →   send_whatsapp_waitlist_offer
        send_custom_reminder_email      →   send_whatsapp_reminder

    WhatsApp tasks are dispatched from inside the email tasks (dual-dispatch).
    They only fire if the guest has a phone number.

    Messages are plain text (WhatsApp doesn't support HTML).
    Each message is logged to notification_logs with channel="whatsapp".
"""

import logging
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.celery_app import app
from app.config import settings
from app.models.guest import Guest
from app.models.event import Event
from app.models.microsite import Microsite

logger = logging.getLogger(__name__)

# ─── Synchronous DB engine for Celery (same as email_tasks.py) ────────────────
SYNC_DB_URL = settings.DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")
sync_engine = create_engine(SYNC_DB_URL, pool_pre_ping=True)
SyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)


def _format_phone(phone: str) -> str:
    """
    Ensure phone is in WhatsApp format: whatsapp:+91XXXXXXXXXX
    Handles various input formats gracefully.
    """
    phone = phone.strip()
    if phone.startswith("whatsapp:"):
        return phone
    if not phone.startswith("+"):
        # Assume Indian number if no country code
        if phone.startswith("0"):
            phone = phone[1:]  # remove leading 0
        phone = f"+91{phone}"
    return f"whatsapp:{phone}"


# ─── Task 1: WhatsApp Invitation ──────────────────────────────────────────────

@app.task(bind=True, max_retries=3)
def send_whatsapp_invitation(self, guest_id: str):
    """
    Send an invitation WhatsApp message with the guest's magic booking link.
    Dispatched from send_guest_invitation_email when guest has a phone number.
    """
    from app.core.notifications.whatsapp import send_whatsapp

    db = SyncSessionLocal()
    try:
        guest = db.execute(
            select(Guest).where(Guest.id == uuid.UUID(guest_id))
        ).scalar_one()

        if not guest.phone:
            logger.info(f"[WA] Skipping invitation for guest {guest_id} — no phone number")
            return

        event = db.execute(
            select(Event).where(Event.id == guest.event_id)
        ).scalar_one()

        microsite = db.execute(
            select(Microsite).where(Microsite.event_id == event.id)
        ).scalar_one_or_none()

        slug = microsite.slug if microsite else str(event.id)
        magic_link = f"https://app.eventflow.com/events/{slug}?token={guest.booking_token}"

        body = (
            f"🎉 *You're Invited!*\n\n"
            f"Hi {guest.name}, you've been invited to *{event.name}* "
            f"({event.start_date} – {event.end_date}).\n\n"
            f"Complete your room booking here:\n{magic_link}\n\n"
            f"This link is unique to you. Do not share it.\n"
            f"— Eventflow"
        )

        send_whatsapp(
            to=_format_phone(guest.phone),
            body=body,
            notification_type="invitation",
            event_id=event.id,
            guest_id=guest.id,
            db=db,
        )

    except Exception as exc:
        logger.error(f"send_whatsapp_invitation failed for guest {guest_id}: {exc}")
        db.rollback()
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


# ─── Task 2: WhatsApp Booking Confirmation ─────────────────────────────────────

@app.task(bind=True, max_retries=3)
def send_whatsapp_booking_confirmation(self, booking_id: str):
    """
    Send a booking confirmation WhatsApp message.
    Dispatched from send_booking_confirmation_email.
    """
    from app.models.booking import Booking
    from app.core.notifications.whatsapp import send_whatsapp

    db = SyncSessionLocal()
    try:
        booking = db.execute(
            select(Booking).where(Booking.id == uuid.UUID(booking_id))
        ).scalar_one()

        guest = db.execute(
            select(Guest).where(Guest.id == booking.guest_id)
        ).scalar_one()

        if not guest.phone:
            logger.info(f"[WA] Skipping confirmation for guest {guest.id} — no phone")
            return

        event = db.execute(
            select(Event).where(Event.id == booking.event_id)
        ).scalar_one()

        amount_due = float(booking.amount_due) if booking.amount_due else 0
        subsidy_line = ""
        if booking.subsidy_applied and float(booking.subsidy_applied) > 0:
            subsidy_line = f"\n• Corporate Subsidy: -₹{float(booking.subsidy_applied):,.0f}"

        body = (
            f"✅ *Booking Confirmed!*\n\n"
            f"Hi {guest.name}, your room is set for *{event.name}*:\n"
            f"• Room: {booking.room_type.title()}\n"
            f"• Check-in: {booking.check_in_date}\n"
            f"• Check-out: {booking.check_out_date}\n"
            f"• Nights: {booking.num_nights}\n"
            f"• Rate/Night: ₹{float(booking.room_rate_per_night):,.0f}\n"
            f"• Total: ₹{float(booking.total_cost):,.0f}"
            f"{subsidy_line}\n"
            f"• *Amount Due: ₹{amount_due:,.0f}*\n\n"
            f"Booking ID: {booking.id}\n"
            f"Carry a valid photo ID at check-in.\n"
            f"— Eventflow"
        )

        send_whatsapp(
            to=_format_phone(guest.phone),
            body=body,
            notification_type="booking_confirmation",
            event_id=booking.event_id,
            guest_id=booking.guest_id,
            db=db,
        )

    except Exception as exc:
        logger.error(f"send_whatsapp_booking_confirmation failed for booking {booking_id}: {exc}")
        db.rollback()
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


# ─── Task 3: WhatsApp Waitlist Offer ───────────────────────────────────────────

@app.task(bind=True, max_retries=3)
def send_whatsapp_waitlist_offer(self, waitlist_id: str):
    """
    Send a "room available" WhatsApp message to the next person on the waitlist.
    Dispatched from send_waitlist_offer_email.
    """
    from app.models.waitlist import Waitlist
    from app.core.notifications.whatsapp import send_whatsapp

    db = SyncSessionLocal()
    try:
        w_entry = db.execute(
            select(Waitlist).where(Waitlist.id == uuid.UUID(waitlist_id))
        ).scalar_one()

        guest = db.execute(
            select(Guest).where(Guest.id == w_entry.guest_id)
        ).scalar_one()

        if not guest.phone:
            logger.info(f"[WA] Skipping waitlist offer for guest {guest.id} — no phone")
            return

        event = db.execute(
            select(Event).where(Event.id == w_entry.event_id)
        ).scalar_one()

        microsite = db.execute(
            select(Microsite).where(Microsite.event_id == event.id)
        ).scalar_one_or_none()

        slug = microsite.slug if microsite else str(event.id)
        booking_link = f"https://app.eventflow.com/events/{slug}?token={guest.booking_token}"

        expires_display = (
            w_entry.offer_expires_at.strftime("%d %b %Y at %I:%M %p UTC")
            if w_entry.offer_expires_at else "24 hours from now"
        )

        body = (
            f"🏨 *A Room is Now Available!*\n\n"
            f"Hi {guest.name}, a *{w_entry.room_type.title()}* room just became "
            f"available for *{event.name}*.\n\n"
            f"You were next on the waitlist!\n\n"
            f"⏰ You have until *{expires_display}* to book.\n"
            f"After that, the room goes to the next person.\n\n"
            f"Book now: {booking_link}\n\n"
            f"— Eventflow"
        )

        send_whatsapp(
            to=_format_phone(guest.phone),
            body=body,
            notification_type="waitlist_offer",
            event_id=w_entry.event_id,
            guest_id=w_entry.guest_id,
            db=db,
        )

    except Exception as exc:
        logger.error(f"send_whatsapp_waitlist_offer failed for waitlist {waitlist_id}: {exc}")
        db.rollback()
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


# ─── Task 4: WhatsApp Custom Reminder (Blast) ─────────────────────────────────

@app.task(bind=True, max_retries=3)
def send_whatsapp_reminder(self, guest_id: str, event_id: str, custom_message: str | None = None):
    """
    Send a custom reminder WhatsApp message.
    Dispatched from send_custom_reminder_email (Phase 6 blast).
    """
    from app.core.notifications.whatsapp import send_whatsapp

    db = SyncSessionLocal()
    try:
        guest = db.execute(
            select(Guest).where(Guest.id == uuid.UUID(guest_id))
        ).scalar_one()

        if not guest.phone:
            logger.info(f"[WA] Skipping reminder for guest {guest_id} — no phone")
            return

        event = db.execute(
            select(Event).where(Event.id == uuid.UUID(event_id))
        ).scalar_one()

        microsite = db.execute(
            select(Microsite).where(Microsite.event_id == event.id)
        ).scalar_one_or_none()

        slug = microsite.slug if microsite else str(event.id)
        booking_link = f"https://app.eventflow.com/events/{slug}?token={guest.booking_token}"

        planner_msg = ""
        if custom_message:
            planner_msg = f'\nYour planner says:\n"{custom_message}"\n'

        body = (
            f"⏰ *Action Required — {event.name}*\n\n"
            f"Hi {guest.name}, please complete your room booking for "
            f"*{event.name}* ({event.start_date} – {event.end_date})."
            f"{planner_msg}\n"
            f"Book now: {booking_link}\n\n"
            f"— Eventflow"
        )

        send_whatsapp(
            to=_format_phone(guest.phone),
            body=body,
            notification_type="manual_blast",
            event_id=event.id,
            guest_id=guest.id,
            db=db,
        )

    except Exception as exc:
        logger.error(f"send_whatsapp_reminder failed for guest {guest_id}: {exc}")
        db.rollback()
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()
