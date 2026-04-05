import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.rbac import require_role
from app.db.session import get_db
from app.models.user import User
from app.models.notification import NotificationLog
from app.schemas.notifications import ReminderBlastRequest

router = APIRouter(tags=["Notifications"])

@router.get(
    "/events/{event_id}/notifications",
    summary="List all email notification logs for an event"
)
async def get_notification_logs(
    event_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    type_filter: Optional[str] = Query(None, description="Filter by type (e.g. 'invitation')"),
    current_user: User = Depends(require_role(["admin", "planner"])),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns an audit log of all communications sent by the background Celery workers.
    """
    stmt = select(NotificationLog).where(NotificationLog.event_id == event_id)
    
    if type_filter:
        stmt = stmt.where(NotificationLog.type == type_filter)
        
    stmt = stmt.order_by(NotificationLog.created_at.desc()).limit(limit).offset(offset)
    
    result = await db.execute(stmt)
    logs = result.scalars().all()
    
    # Simple dictionary dump
    items = []
    for log in logs:
        items.append({
            "id": str(log.id),
            "guest_id": str(log.guest_id) if log.guest_id else None,
            "type": log.type,
            "channel": log.channel,
            "status": log.status,
            "recipient_email": log.recipient_email,
            "provider_message_id": log.provider_message_id,
            "error_message": log.error_message,
            "sent_at": log.sent_at,
            "created_at": log.created_at
        })
        
    return {"items": items, "count": len(items)}


# ══════════════════════════════════════════════════════════════════════════════
# Phase 6: Manual Reminder Blast
# ══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/events/{event_id}/reminders/blast",
    summary="Send manual reminder blast to specific guest categories",
    status_code=status.HTTP_200_OK,
)
async def reminder_blast(
    event_id: uuid.UUID,
    body: ReminderBlastRequest,
    current_user: User = Depends(require_role(["admin", "planner"])),
    db: AsyncSession = Depends(get_db),
):
    """
    Send a manual reminder email blast to all unbooked guests in the specified categories.

    The planner sees the analytics dashboard showing 60% of VIPs haven't booked.
    They hit this endpoint with categories=["vip"] and an optional custom_message.
    The system finds all unbooked guests in those categories, queues one Celery
    email task per guest, and returns immediately with the count.

    Request body:
        {
            "categories": ["vip", "family"],
            "custom_message": "VIP rooms are filling up fast. Please confirm by Friday."
        }

    Returns:
        { "queued": 47, "categories": ["vip", "family"], "event_name": "Acme Offsite" }
    """
    from app.models.event import Event
    from app.models.guest import Guest
    from app.models.booking import Booking
    from app.schemas.notifications import ReminderBlastRequest, ReminderBlastResponse
    from app.tasks.email_tasks import send_custom_reminder_email

    # Verify event exists and belongs to this tenant
    event_result = await db.execute(
        select(Event).where(Event.id == event_id, Event.tenant_id == current_user.tenant_id)
    )
    event = event_result.scalar_one_or_none()
    if not event:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Event not found")

    # Subquery: guests who already have an active booking
    booked_guest_ids = (
        select(Booking.guest_id).where(
            Booking.event_id == event_id,
            Booking.status.in_(["HELD", "CONFIRMED", "CHECKED_IN"]),
        )
    )

    # Find unbooked guests in the specified categories with email addresses
    stmt = select(Guest).where(
        Guest.event_id == event_id,
        Guest.is_active == True,           # noqa: E712
        Guest.email.isnot(None),
        Guest.category.in_(body.categories),
        ~Guest.id.in_(booked_guest_ids),
    )

    result = await db.execute(stmt)
    guests = result.scalars().all()

    # Queue one email task per guest (isolated — any single failure doesn't block others)
    queued = 0
    for guest in guests:
        send_custom_reminder_email.delay(
            str(guest.id),
            str(event_id),
            body.custom_message,
        )
        queued += 1

    return {
        "queued": queued,
        "categories": body.categories,
        "event_name": event.name,
    }

