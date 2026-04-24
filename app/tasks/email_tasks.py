"""
Eventflow Email Tasks — Celery background jobs that send real emails via Resend.

Architecture note:
    Celery workers are separate OS processes with no shared asyncio event loop.
    We CANNOT use the async SQLAlchemy engine here — it causes socket conflicts.
    Solution: create a dedicated synchronous engine (psycopg2) just for Celery tasks.

Email strategy:
    - If RESEND_API_KEY is set in .env → sends real emails via resend.com
    - If not set → logs a "Mock Email Sent" warning (safe during initial local dev)

All sent emails are logged to the notification_logs table with:
    - provider_message_id (Resend's message ID for tracking)
    - status: "success" | "failed"
    - recipient_email, type, sent_at
"""

import logging
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

# ─── Resend SDK init ───────────────────────────────────────────────────────────
if settings.RESEND_API_KEY:
    resend.api_key = settings.RESEND_API_KEY
    logger.info("Resend SDK initialized — real emails will be sent.")
else:
    logger.warning("RESEND_API_KEY not set — falling back to mock email logging.")

# ─── Synchronous DB engine for Celery ─────────────────────────────────────────
# Celery runs tasks in isolated OS worker processes/threads, and mixing
# asyncio.run() with a global async_engine causes severe asyncpg socket conflicts.
# By using pure blocking psycopg2 queries, we guarantee perfect stability.
SYNC_DB_URL = settings.DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")
# psycopg2 uses 'sslmode=require' but asyncpg uses 'ssl=require' — fix that
SYNC_DB_URL = SYNC_DB_URL.replace("ssl=require", "sslmode=require")
sync_engine = create_engine(SYNC_DB_URL, pool_pre_ping=True)
SyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)


# ─── Internal helper ──────────────────────────────────────────────────────────

def _send_email_or_mock(*, to: str, subject: str, html: str, notification_type: str,
                         event_id, guest_id, db) -> None:
    """
    Central dispatch: sends via Resend if API key is configured, otherwise mocks.
    Always writes to notification_logs.

    RESEND_TEST_OVERRIDE_TO: If set in settings, ALL emails are physically delivered
    to that single address regardless of `to`. The original guest email is still
    stored in notification_logs. Subject is prefixed with [original@email] so the
    inbox is readable and you can tell which guest/type each email is for.
    """
    provider_message_id = None
    status = "success"
    error_message = None

    # Determine actual delivery address (override for test mode)
    actual_to = settings.RESEND_TEST_OVERRIDE_TO if settings.RESEND_TEST_OVERRIDE_TO else to
    send_subject = subject
    if actual_to != to:
        # Prefix subject so you can read the inbox easily:
        # "[charlie@e2e.com] Room Available — Book Now for E2E Offsite"
        send_subject = f"[{to}] {subject}"
        logger.info(f"[Resend] TEST OVERRIDE: '{notification_type}' intended for {to} → redirected to {actual_to}")

    if settings.RESEND_API_KEY:
        try:
            response = resend.Emails.send({
                "from": settings.RESEND_FROM_EMAIL,
                "to": actual_to,
                "subject": send_subject,
                "html": html,
            })
            provider_message_id = response.get("id")
            logger.info(f"[Resend] Sent '{notification_type}' to {actual_to} | msg_id={provider_message_id}")
        except Exception as e:
            status = "failed"
            error_message = str(e)
            logger.error(f"[Resend] Failed to send '{notification_type}' to {actual_to}: {e}")
    else:
        logger.info(f"[Mock] '{notification_type}' → {actual_to} | subject='{send_subject}'")
        logger.info(f"[Mock] HTML preview:\n{html[:300]}...")

    log_entry = NotificationLog(
        event_id=event_id,
        guest_id=guest_id,
        type=notification_type,
        status=status,
        recipient_email=to,
        provider_message_id=provider_message_id,
        error_message=error_message,
        sent_at=datetime.utcnow(),
    )
    db.add(log_entry)
    db.commit()


# ─── Task 1: Guest Invitation ──────────────────────────────────────────────────

@app.task(bind=True, max_retries=3)
def send_guest_invitation_email(self, guest_id: str):
    """
    Send an invitation email containing the guest's magic booking link.
    Triggered automatically when a guest is created (single or bulk import).
    """
    db = SyncSessionLocal()
    try:
        guest = db.execute(
            select(Guest).where(Guest.id == uuid.UUID(guest_id))
        ).scalar_one()

        event = db.execute(
            select(Event).where(Event.id == guest.event_id)
        ).scalar_one()

        microsite = db.execute(
            select(Microsite).where(Microsite.event_id == event.id)
        ).scalar_one_or_none()

        slug = microsite.slug if microsite else str(event.id)
        magic_link = f"https://app.eventflow.com/events/{slug}?token={guest.booking_token}"

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1a1a1a;">
            <div style="background: linear-gradient(135deg, #667eea, #764ba2); padding: 32px; border-radius: 12px 12px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 24px;">You're Invited! 🎉</h1>
                <p style="color: rgba(255,255,255,0.85); margin: 8px 0 0 0;">{event.name}</p>
            </div>
            <div style="background: #ffffff; padding: 32px; border-radius: 0 0 12px 12px; border: 1px solid #e5e7eb;">
                <p style="font-size: 16px;">Hello <strong>{guest.name}</strong>,</p>
                <p style="color: #4b5563; line-height: 1.6;">
                    You have been invited to <strong>{event.name}</strong>
                    ({event.start_date} – {event.end_date}).
                    Click the button below to view the event details and complete your room booking.
                </p>
                <p style="color: #6b7280; font-size: 14px;">
                    Your booking is personalized for you — no login required.
                </p>
                <div style="text-align: center; margin: 32px 0;">
                    <a href="{magic_link}"
                       style="background: #667eea; color: white; padding: 14px 32px;
                              border-radius: 8px; text-decoration: none; font-weight: 600;
                              font-size: 16px; display: inline-block;">
                        Complete Your Booking →
                    </a>
                </div>
                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;" />
                <p style="color: #9ca3af; font-size: 12px; text-align: center;">
                    This link is unique to you. Please do not share it.<br>
                    Eventflow · Group Travel Infrastructure
                </p>
            </div>
        </body>
        </html>
        """

        _send_email_or_mock(
            to=guest.email,
            subject=f"Your Invitation to {event.name}",
            html=html,
            notification_type="invitation",
            event_id=event.id,
            guest_id=guest.id,
            db=db,
        )

        # Phase 8: Dual-dispatch WhatsApp (if guest has phone)
        if guest.phone:
            from app.tasks.whatsapp_tasks import send_whatsapp_invitation
            send_whatsapp_invitation.delay(str(guest.id))

    except Exception as exc:
        logger.error(f"send_guest_invitation_email failed for guest {guest_id}: {exc}")
        db.rollback()
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


# ─── Task 2: Booking Confirmation ─────────────────────────────────────────────

@app.task(bind=True, max_retries=3)
def send_booking_confirmation_email(self, booking_id: str):
    """
    Send a confirmation email after a guest's hold is CONFIRMED.
    Triggered by confirm_hold() in the booking service.
    """
    from app.models.booking import Booking

    db = SyncSessionLocal()
    try:
        booking = db.execute(
            select(Booking).where(Booking.id == uuid.UUID(booking_id))
        ).scalar_one()

        guest = db.execute(
            select(Guest).where(Guest.id == booking.guest_id)
        ).scalar_one()

        event = db.execute(
            select(Event).where(Event.id == booking.event_id)
        ).scalar_one()

        subsidy_line = ""
        if booking.subsidy_applied and float(booking.subsidy_applied) > 0:
            subsidy_line = f"""
            <tr>
                <td style="padding: 8px 0; color: #6b7280;">Corporate Subsidy</td>
                <td style="padding: 8px 0; text-align: right; color: #10b981;">
                    - ₹{float(booking.subsidy_applied):,.0f}
                </td>
            </tr>
            """

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1a1a1a;">
            <div style="background: #10b981; padding: 32px; border-radius: 12px 12px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 24px;">Booking Confirmed ✅</h1>
                <p style="color: rgba(255,255,255,0.85); margin: 8px 0 0 0;">{event.name}</p>
            </div>
            <div style="background: #ffffff; padding: 32px; border-radius: 0 0 12px 12px; border: 1px solid #e5e7eb;">
                <p style="font-size: 16px;">Hi <strong>{guest.name}</strong>, your room is confirmed! 🎊</p>

                <div style="background: #f9fafb; border-radius: 8px; padding: 20px; margin: 20px 0;">
                    <h3 style="margin: 0 0 16px 0; font-size: 15px; color: #374151;">Booking Summary</h3>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 8px 0; color: #6b7280;">Room Type</td>
                            <td style="padding: 8px 0; text-align: right; font-weight: 600;">
                                {booking.room_type.title()}
                            </td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; color: #6b7280;">Check-In</td>
                            <td style="padding: 8px 0; text-align: right;">{booking.check_in_date}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; color: #6b7280;">Check-Out</td>
                            <td style="padding: 8px 0; text-align: right;">{booking.check_out_date}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; color: #6b7280;">Nights</td>
                            <td style="padding: 8px 0; text-align: right;">{booking.num_nights}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; color: #6b7280;">Rate / Night</td>
                            <td style="padding: 8px 0; text-align: right;">₹{float(booking.room_rate_per_night):,.0f}</td>
                        </tr>
                        <tr style="border-top: 1px solid #e5e7eb;">
                            <td style="padding: 8px 0; color: #6b7280;">Total Cost</td>
                            <td style="padding: 8px 0; text-align: right;">₹{float(booking.total_cost):,.0f}</td>
                        </tr>
                        {subsidy_line}
                        <tr style="background: #ecfdf5; border-radius: 4px;">
                            <td style="padding: 10px 8px; font-weight: 700; color: #065f46;">Amount Due from You</td>
                            <td style="padding: 10px 8px; text-align: right; font-weight: 700; font-size: 18px; color: #059669;">
                                ₹{float(booking.amount_due):,.0f}
                            </td>
                        </tr>
                    </table>
                </div>

                <p style="color: #6b7280; font-size: 14px; line-height: 1.6;">
                    Please carry a valid photo ID at check-in. If you need to make changes,
                    contact your event planner.
                </p>

                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;" />
                <p style="color: #9ca3af; font-size: 12px; text-align: center;">
                    Booking ID: {booking.id}<br>
                    Eventflow · Group Travel Infrastructure
                </p>
            </div>
        </body>
        </html>
        """

        _send_email_or_mock(
            to=guest.email,
            subject=f"Booking Confirmed — {event.name}",
            html=html,
            notification_type="booking_confirmation",
            event_id=booking.event_id,
            guest_id=booking.guest_id,
            db=db,
        )

        # Phase 8: Dual-dispatch WhatsApp (if guest has phone)
        if guest.phone:
            from app.tasks.whatsapp_tasks import send_whatsapp_booking_confirmation
            send_whatsapp_booking_confirmation.delay(str(booking.id))

    except Exception as exc:
        logger.error(f"send_booking_confirmation_email failed for booking {booking_id}: {exc}")
        db.rollback()
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


# ─── Task 3: Waitlist Offer ────────────────────────────────────────────────────

@app.task(bind=True, max_retries=3)
def send_waitlist_offer_email(self, waitlist_id: str):
    """
    Send a "room is now available" email to the next person on the waitlist.
    Triggered by promote_next() inside the cancellation flow.
    The guest has 24 hours to click and complete their booking.
    """
    from app.models.waitlist import Waitlist

    db = SyncSessionLocal()
    try:
        w_entry = db.execute(
            select(Waitlist).where(Waitlist.id == uuid.UUID(waitlist_id))
        ).scalar_one()

        guest = db.execute(
            select(Guest).where(Guest.id == w_entry.guest_id)
        ).scalar_one()

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

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1a1a1a;">
            <div style="background: linear-gradient(135deg, #f59e0b, #ef4444); padding: 32px; border-radius: 12px 12px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 24px;">A Room is Now Available! 🏨</h1>
                <p style="color: rgba(255,255,255,0.9); margin: 8px 0 0 0;">{event.name}</p>
            </div>
            <div style="background: #ffffff; padding: 32px; border-radius: 0 0 12px 12px; border: 1px solid #e5e7eb;">
                <p style="font-size: 16px;">Hi <strong>{guest.name}</strong>,</p>
                <p style="color: #4b5563; line-height: 1.6;">
                    Great news! A <strong>{w_entry.room_type.title()}</strong> room just became available
                    for <strong>{event.name}</strong>. You were next on the waitlist.
                </p>

                <div style="background: #fef3c7; border: 1px solid #f59e0b; border-radius: 8px; padding: 16px; margin: 20px 0;">
                    <p style="margin: 0; color: #92400e; font-weight: 600; font-size: 15px;">
                        ⏰ You have until <strong>{expires_display}</strong> to complete your booking.
                    </p>
                    <p style="margin: 8px 0 0 0; color: #92400e; font-size: 14px;">
                        After this, the room will be offered to the next person on the waitlist.
                    </p>
                </div>

                <div style="text-align: center; margin: 32px 0;">
                    <a href="{booking_link}"
                       style="background: #ef4444; color: white; padding: 14px 32px;
                              border-radius: 8px; text-decoration: none; font-weight: 600;
                              font-size: 16px; display: inline-block;">
                        Book My Room Now →
                    </a>
                </div>

                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;" />
                <p style="color: #9ca3af; font-size: 12px; text-align: center;">
                    Eventflow · Group Travel Infrastructure
                </p>
            </div>
        </body>
        </html>
        """

        _send_email_or_mock(
            to=guest.email,
            subject=f"Room Available — Book Now for {event.name}",
            html=html,
            notification_type="waitlist_offer",
            event_id=w_entry.event_id,
            guest_id=w_entry.guest_id,
            db=db,
        )

        # Phase 8: Dual-dispatch WhatsApp (if guest has phone)
        if guest.phone:
            from app.tasks.whatsapp_tasks import send_whatsapp_waitlist_offer
            send_whatsapp_waitlist_offer.delay(str(w_entry.id))

    except Exception as exc:
        logger.error(f"send_waitlist_offer_email failed for waitlist {waitlist_id}: {exc}")
        db.rollback()
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


# ─── Task 4: Booking Reminder ──────────────────────────────────────────────────

@app.task(bind=True, max_retries=3)
def send_booking_reminder_email(self, guest_id: str, days_left: int):
    """
    Send a deadline reminder to a guest who hasn't booked yet.
    Called by the booking_reminder_sequence cron task for days_left ∈ {7, 3, 1}.

    Tone deliberately escalates:
    - 7 days: informational nudge
    - 3 days: urgency
    - 1 day: final warning
    """
    db = SyncSessionLocal()
    try:
        guest = db.execute(
            select(Guest).where(Guest.id == uuid.UUID(guest_id))
        ).scalar_one()

        event = db.execute(
            select(Event).where(Event.id == guest.event_id)
        ).scalar_one()

        microsite = db.execute(
            select(Microsite).where(Microsite.event_id == event.id)
        ).scalar_one_or_none()

        slug = microsite.slug if microsite else str(event.id)
        booking_link = f"https://app.eventflow.com/events/{slug}?token={guest.booking_token}"

        # Escalate tone based on days left
        if days_left == 7:
            urgency_color = "#3b82f6"
            urgency_label = "7 Days Remaining"
            urgency_message = "Your accommodation booking window is coming up. Take a moment to secure your room."
            cta_text = "Book My Room"
            subject = f"Reminder: Book Your Room for {event.name}"
        elif days_left == 3:
            urgency_color = "#f59e0b"
            urgency_label = "Only 3 Days Left!"
            urgency_message = "Rooms are filling up fast. Please complete your booking before the deadline."
            cta_text = "Book Now — 3 Days Left"
            subject = f"⚡ 3 Days Left to Book — {event.name}"
        else:  # 1 day
            urgency_color = "#ef4444"
            urgency_label = "Last Chance — Deadline Tomorrow!"
            urgency_message = "This is your final reminder. The booking window closes tomorrow. After that, we cannot guarantee accommodation."
            cta_text = "Book TODAY — Final Deadline"
            subject = f"🚨 FINAL REMINDER: Book Today for {event.name}"

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1a1a1a;">
            <div style="background: {urgency_color}; padding: 32px; border-radius: 12px 12px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 22px;">{urgency_label}</h1>
                <p style="color: rgba(255,255,255,0.9); margin: 8px 0 0 0;">{event.name}</p>
            </div>
            <div style="background: #ffffff; padding: 32px; border-radius: 0 0 12px 12px; border: 1px solid #e5e7eb;">
                <p style="font-size: 16px;">Hi <strong>{guest.name}</strong>,</p>
                <p style="color: #4b5563; line-height: 1.6;">{urgency_message}</p>

                <div style="background: #f9fafb; border-radius: 8px; padding: 16px; margin: 20px 0;">
                    <table style="width: 100%;">
                        <tr>
                            <td style="color: #6b7280; padding: 4px 0;">Event</td>
                            <td style="text-align: right; font-weight: 600;">{event.name}</td>
                        </tr>
                        <tr>
                            <td style="color: #6b7280; padding: 4px 0;">Dates</td>
                            <td style="text-align: right;">{event.start_date} – {event.end_date}</td>
                        </tr>
                        <tr>
                            <td style="color: #6b7280; padding: 4px 0;">Your Category</td>
                            <td style="text-align: right;">{guest.category.title()}</td>
                        </tr>
                    </table>
                </div>

                <div style="text-align: center; margin: 32px 0;">
                    <a href="{booking_link}"
                       style="background: {urgency_color}; color: white; padding: 14px 32px;
                              border-radius: 8px; text-decoration: none; font-weight: 600;
                              font-size: 16px; display: inline-block;">
                        {cta_text} →
                    </a>
                </div>

                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;" />
                <p style="color: #9ca3af; font-size: 12px; text-align: center;">
                    Eventflow · Group Travel Infrastructure
                </p>
            </div>
        </body>
        </html>
        """

        _send_email_or_mock(
            to=guest.email,
            subject=subject,
            html=html,
            notification_type=f"reminder_{days_left}d",
            event_id=guest.event_id,
            guest_id=guest.id,
            db=db,
        )

    except Exception as exc:
        logger.error(f"send_booking_reminder_email failed for guest {guest_id}: {exc}")
        db.rollback()
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


# ─── Task 5: Manual Custom Reminder (Phase 6 — Reminder Blast) ────────────────

@app.task(bind=True, max_retries=3)
def send_custom_reminder_email(self, guest_id: str, event_id: str, custom_message: str | None = None):
    """
    Send a one-off custom reminder to a specific guest.
    Triggered by the POST /events/{id}/reminders/blast endpoint.
    The planner picks categories + writes a custom message.
    """
    db = SyncSessionLocal()
    try:
        guest = db.execute(
            select(Guest).where(Guest.id == uuid.UUID(guest_id))
        ).scalar_one()

        event = db.execute(
            select(Event).where(Event.id == uuid.UUID(event_id))
        ).scalar_one()

        microsite = db.execute(
            select(Microsite).where(Microsite.event_id == event.id)
        ).scalar_one_or_none()

        slug = microsite.slug if microsite else str(event.id)
        booking_link = f"https://app.eventflow.com/events/{slug}?token={guest.booking_token}"

        message_html = ""
        if custom_message:
            message_html = f"""
            <div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 16px; margin: 20px 0; border-radius: 0 8px 8px 0;">
                <p style="margin: 0; color: #92400e; font-style: italic;">"{custom_message}"</p>
                <p style="margin: 8px 0 0 0; color: #b45309; font-size: 13px;">— Your Event Planner</p>
            </div>
            """

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1a1a1a;">
            <div style="background: linear-gradient(135deg, #8b5cf6, #6d28d9); padding: 32px; border-radius: 12px 12px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 22px;">Action Required</h1>
                <p style="color: rgba(255,255,255,0.9); margin: 8px 0 0 0;">{event.name}</p>
            </div>
            <div style="background: #ffffff; padding: 32px; border-radius: 0 0 12px 12px; border: 1px solid #e5e7eb;">
                <p style="font-size: 16px;">Hi <strong>{guest.name}</strong>,</p>
                <p style="color: #4b5563; line-height: 1.6;">
                    Your event planner would like to remind you to complete your room booking
                    for <strong>{event.name}</strong> ({event.start_date} – {event.end_date}).
                </p>

                {message_html}

                <div style="text-align: center; margin: 32px 0;">
                    <a href="{booking_link}"
                       style="background: #8b5cf6; color: white; padding: 14px 32px;
                              border-radius: 8px; text-decoration: none; font-weight: 600;
                              font-size: 16px; display: inline-block;">
                        Complete My Booking →
                    </a>
                </div>

                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;" />
                <p style="color: #9ca3af; font-size: 12px; text-align: center;">
                    Eventflow · Group Travel Infrastructure
                </p>
            </div>
        </body>
        </html>
        """

        _send_email_or_mock(
            to=guest.email,
            subject=f"Reminder: Complete Your Booking — {event.name}",
            html=html,
            notification_type="manual_blast",
            event_id=event.id,
            guest_id=guest.id,
            db=db,
        )

        # Phase 8: Dual-dispatch WhatsApp (if guest has phone)
        if guest.phone:
            from app.tasks.whatsapp_tasks import send_whatsapp_reminder
            send_whatsapp_reminder.delay(str(guest.id), str(event.id), custom_message)

    except Exception as exc:
        logger.error(f"send_custom_reminder_email failed for guest {guest_id}: {exc}")
        db.rollback()
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


# ─── Task 6: Event Completion Summary (Phase 6 — Auto-Completion) ─────────────

@app.task(bind=True, max_retries=3)
def send_event_completion_email(self, event_id: str, summary_data: dict):
    """
    Send a completion summary email to the planner/admin.
    Triggered by the event_auto_completion cron task when hold_deadline passes.

    summary_data contains: confirmed_rooms, released_rooms, room_breakdown, event_name, etc.
    """
    from app.models.user import User
    from app.models.tenant import Tenant

    db = SyncSessionLocal()
    try:
        event = db.execute(
            select(Event).where(Event.id == uuid.UUID(event_id))
        ).scalar_one()

        # Find the admin users for this tenant to email
        admin_result = db.execute(
            select(User).where(
                User.tenant_id == event.tenant_id,
                User.role.in_(["admin", "planner"]),
                User.is_active == True,
            )
        )
        admins = admin_result.scalars().all()

        if not admins:
            logger.warning(f"No admin/planner found for tenant of event {event_id}")
            return

        confirmed = summary_data.get("confirmed_rooms", 0)
        released = summary_data.get("released_rooms", 0)
        breakdown = summary_data.get("room_breakdown", [])
        venue_name = summary_data.get("venue_name", "the venue")

        breakdown_html = ""
        for item in breakdown:
            breakdown_html += f"""
            <tr>
                <td style="padding: 8px 0; color: #6b7280;">{item['room_type'].title()}</td>
                <td style="padding: 8px 0; text-align: right;">{item['booked']}</td>
                <td style="padding: 8px 0; text-align: right; color: #ef4444;">{item['released']}</td>
            </tr>
            """

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1a1a1a;">
            <div style="background: linear-gradient(135deg, #059669, #10b981); padding: 32px; border-radius: 12px 12px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 24px;">Event Complete ✅</h1>
                <p style="color: rgba(255,255,255,0.9); margin: 8px 0 0 0;">{event.name}</p>
            </div>
            <div style="background: #ffffff; padding: 32px; border-radius: 0 0 12px 12px; border: 1px solid #e5e7eb;">
                <p style="font-size: 16px;">The booking deadline for <strong>{event.name}</strong> has passed.</p>

                <div style="background: #f0fdf4; border-radius: 8px; padding: 20px; margin: 20px 0; text-align: center;">
                    <div style="font-size: 48px; font-weight: 700; color: #059669;">{confirmed}</div>
                    <div style="color: #6b7280; font-size: 14px;">Rooms Confirmed</div>
                </div>

                <div style="background: #f9fafb; border-radius: 8px; padding: 16px; margin: 16px 0;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <th style="padding: 8px 0; text-align: left; color: #374151; font-size: 13px;">Room Type</th>
                            <th style="padding: 8px 0; text-align: right; color: #374151; font-size: 13px;">Confirmed</th>
                            <th style="padding: 8px 0; text-align: right; color: #374151; font-size: 13px;">Released</th>
                        </tr>
                        {breakdown_html}
                    </table>
                </div>

                <p style="color: #4b5563; line-height: 1.6;">
                    <strong>{released} rooms</strong> have been released back to <strong>{venue_name}</strong>.
                    The rooming list CSV is attached to a separate email or can be downloaded from your dashboard.
                </p>

                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;" />
                <p style="color: #9ca3af; font-size: 12px; text-align: center;">
                    Eventflow · Group Travel Infrastructure
                </p>
            </div>
        </body>
        </html>
        """

        for admin in admins:
            if admin.email:
                _send_email_or_mock(
                    to=admin.email,
                    subject=f"Event Complete — {event.name} | {confirmed} rooms confirmed, {released} released",
                    html=html,
                    notification_type="event_completion",
                    event_id=event.id,
                    guest_id=None,
                    db=db,
                )

    except Exception as exc:
        logger.error(f"send_event_completion_email failed for event {event_id}: {exc}")
        db.rollback()
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()


# ─── Task 7: Hotel Handoff Summary (Phase 6 — Auto-Completion) ────────────────

@app.task(bind=True, max_retries=3)
def send_hotel_handoff_email(self, event_id: str, venue_email: str, summary_data: dict):
    """
    Send a summary + rooming count to the hotel venue contact.
    Only fires if the venue has a contact_email set.
    """
    db = SyncSessionLocal()
    try:
        event = db.execute(
            select(Event).where(Event.id == uuid.UUID(event_id))
        ).scalar_one()

        confirmed = summary_data.get("confirmed_rooms", 0)
        released = summary_data.get("released_rooms", 0)
        breakdown = summary_data.get("room_breakdown", [])
        venue_name = summary_data.get("venue_name", "Hotel")
        check_in = summary_data.get("check_in_date", "TBD")
        check_out = summary_data.get("check_out_date", "TBD")
        planner_email = summary_data.get("planner_email", "")

        breakdown_html = ""
        for item in breakdown:
            breakdown_html += f"""
            <tr>
                <td style="padding: 8px 12px; border-bottom: 1px solid #e5e7eb;">{item['room_type'].title()}</td>
                <td style="padding: 8px 12px; border-bottom: 1px solid #e5e7eb; text-align: right;">{item['booked']}</td>
                <td style="padding: 8px 12px; border-bottom: 1px solid #e5e7eb; text-align: right;">{item['released']}</td>
            </tr>
            """

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1a1a1a;">
            <div style="background: #1e293b; padding: 32px; border-radius: 12px 12px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 22px;">Final Rooming List 🏨</h1>
                <p style="color: rgba(255,255,255,0.7); margin: 8px 0 0 0;">{event.name}</p>
            </div>
            <div style="background: #ffffff; padding: 32px; border-radius: 0 0 12px 12px; border: 1px solid #e5e7eb;">
                <p style="font-size: 16px;">Dear <strong>{venue_name}</strong> Team,</p>
                <p style="color: #4b5563; line-height: 1.6;">
                    The booking deadline for <strong>{event.name}</strong> has passed.
                    Below is the final room reservation summary.
                </p>

                <div style="background: #f9fafb; border-radius: 8px; padding: 16px; margin: 20px 0;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                        <tr>
                            <td style="padding: 6px 0; color: #6b7280;">Check-In</td>
                            <td style="padding: 6px 0; text-align: right; font-weight: 600;">{check_in}</td>
                        </tr>
                        <tr>
                            <td style="padding: 6px 0; color: #6b7280;">Check-Out</td>
                            <td style="padding: 6px 0; text-align: right; font-weight: 600;">{check_out}</td>
                        </tr>
                        <tr>
                            <td style="padding: 6px 0; color: #6b7280;">Total Confirmed</td>
                            <td style="padding: 6px 0; text-align: right; font-weight: 700; color: #059669;">{confirmed} rooms</td>
                        </tr>
                        <tr>
                            <td style="padding: 6px 0; color: #6b7280;">Released Back to You</td>
                            <td style="padding: 6px 0; text-align: right; font-weight: 600; color: #ef4444;">{released} rooms</td>
                        </tr>
                    </table>
                </div>

                <div style="margin: 20px 0;">
                    <h3 style="font-size: 14px; color: #374151; margin: 0 0 8px;">Room Breakdown</h3>
                    <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                        <tr style="background: #f3f4f6;">
                            <th style="padding: 8px 12px; text-align: left;">Type</th>
                            <th style="padding: 8px 12px; text-align: right;">Confirmed</th>
                            <th style="padding: 8px 12px; text-align: right;">Released</th>
                        </tr>
                        {breakdown_html}
                    </table>
                </div>

                <p style="color: #4b5563; font-size: 14px;">
                    Planner contact: <a href="mailto:{planner_email}">{planner_email}</a>
                </p>

                <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;" />
                <p style="color: #9ca3af; font-size: 12px; text-align: center;">
                    Sent via Eventflow · Group Travel Infrastructure
                </p>
            </div>
        </body>
        </html>
        """

        _send_email_or_mock(
            to=venue_email,
            subject=f"Final Rooming List — {event.name} | {confirmed} rooms confirmed",
            html=html,
            notification_type="hotel_handoff",
            event_id=event.id,
            guest_id=None,
            db=db,
        )

    except Exception as exc:
        logger.error(f"send_hotel_handoff_email failed for event {event_id}: {exc}")
        db.rollback()
        raise self.retry(exc=exc, countdown=60)
    finally:
        db.close()

