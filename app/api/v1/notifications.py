import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.rbac import require_role
from app.db.session import get_db
from app.models.user import User
from app.models.notification import NotificationLog

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
            "status": log.status,
            "recipient_email": log.recipient_email,
            "provider_message_id": log.provider_message_id,
            "error_message": log.error_message,
            "sent_at": log.sent_at,
            "created_at": log.created_at
        })
        
    return {"items": items, "count": len(items)}
