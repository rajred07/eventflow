"""
WhatsApp Client — sends WhatsApp messages via Twilio.

Architecture:
    Same mock/real pattern as the Resend email client:
    - If TWILIO_ACCOUNT_SID is set → sends real WhatsApp messages via Twilio
    - If not set → logs a mock message (safe for dev without Twilio credentials)

    TWILIO_TEST_OVERRIDE_TO: When set, ALL outbound WhatsApp messages are
    redirected to that single phone number (your phone) regardless of the
    guest's actual phone. Same pattern as RESEND_TEST_OVERRIDE_TO for email.

Usage:
    from app.core.notifications.whatsapp import send_whatsapp
    sid = send_whatsapp(to="whatsapp:+919876543210", body="Hello!")
"""

import logging
from datetime import datetime

from app.config import settings

logger = logging.getLogger(__name__)

# Lazy-init Twilio client (only when actually sending)
_twilio_client = None


def _get_twilio_client():
    """Lazily initialize the Twilio client to avoid import-time failures."""
    global _twilio_client
    if _twilio_client is None:
        from twilio.rest import Client
        _twilio_client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    return _twilio_client


def send_whatsapp(*, to: str, body: str, notification_type: str,
                  event_id, guest_id, db) -> str | None:
    """
    Send a WhatsApp message via Twilio. Always logs to notification_logs.

    Args:
        to: Phone number in format "whatsapp:+91XXXXXXXXXX"
        body: Plain text message body (WhatsApp doesn't support HTML)
        notification_type: For logging (e.g., "invitation", "booking_confirmation")
        event_id: UUID of the event
        guest_id: UUID of the guest (nullable for planner-targeted messages)
        db: Synchronous DB session (from Celery context)

    Returns:
        Twilio message SID if sent, None if mocked/failed
    """
    from app.models.notification import NotificationLog

    provider_message_id = None
    status = "success"
    error_message = None

    # Determine actual delivery number (override for test mode)
    actual_to = settings.TWILIO_TEST_OVERRIDE_TO if settings.TWILIO_TEST_OVERRIDE_TO else to
    if actual_to != to:
        logger.info(
            f"[Twilio] TEST OVERRIDE: '{notification_type}' intended for {to} "
            f"→ redirected to {actual_to}"
        )

    if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
        try:
            client = _get_twilio_client()
            message = client.messages.create(
                from_=settings.TWILIO_WHATSAPP_FROM,
                body=body,
                to=actual_to,
            )
            provider_message_id = message.sid
            logger.info(
                f"[Twilio] Sent '{notification_type}' to {actual_to} | sid={provider_message_id}"
            )
        except Exception as e:
            status = "failed"
            error_message = str(e)
            logger.error(f"[Twilio] Failed to send '{notification_type}' to {actual_to}: {e}")
    else:
        logger.info(f"[Mock WA] '{notification_type}' → {actual_to}")
        logger.info(f"[Mock WA] Body: {body[:200]}...")

    # Log to notification_logs — same table as email, different channel
    log_entry = NotificationLog(
        event_id=event_id,
        guest_id=guest_id,
        type=notification_type,
        channel="whatsapp",
        status=status,
        recipient_email=to,  # stores the phone number (field name is legacy from email-only era)
        provider_message_id=provider_message_id,
        error_message=error_message,
        sent_at=datetime.utcnow(),
    )
    db.add(log_entry)
    db.commit()

    return provider_message_id
