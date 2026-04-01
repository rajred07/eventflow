"""
Waitlist Routes — Manage event-level queue when room blocks fill up.

POST /api/v1/events/{event_id}/waitlist        → Add guest to waitlist
GET  /api/v1/events/{event_id}/waitlist        → View paginated waitlist
PUT  /api/v1/waitlists/{id}/status             → Manually change waitlist status
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.rbac import require_role
from app.core.waitlists.service import (
    add_to_waitlist,
    get_waitlist_by_id,
    get_waitlists_for_event,
    update_waitlist_status,
)
from app.db.session import get_db
from app.models.user import User
from app.schemas.waitlist import (
    WaitlistActionRequest,
    WaitlistCreate,
    WaitlistListResponse,
    WaitlistResponse,
)

event_waitlist_router = APIRouter(prefix="/events/{event_id}/waitlist", tags=["Waitlist"])
waitlist_router = APIRouter(prefix="/waitlists", tags=["Waitlist"])


@event_waitlist_router.post(
    "",
    response_model=WaitlistResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add guest to waitlist",
)
async def add_waitlist_route(
    event_id: uuid.UUID,
    data: WaitlistCreate,
    current_user: User = Depends(require_role(["admin", "planner"])),
    db: AsyncSession = Depends(get_db),
):
    """
    Manually add a guest to the waitlist from the planner dashboard.
    (Guests can also auto-add themselves via a public route in Phase 2E).
    """
    try:
        # returns the SQLAlchemy model
        waitlist_obj = await add_to_waitlist(
            data=data,
            tenant_id=current_user.tenant_id,
            event_id=event_id,
            db=db,
        )
        # To get the runtime computed position, we do a fast query read back
        waitlist_dict = await get_waitlist_by_id(
            waitlist_obj.id, current_user.tenant_id, db
        )
        return waitlist_dict
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@event_waitlist_router.get(
    "",
    response_model=WaitlistListResponse,
    summary="List waitlist for an event",
)
async def list_event_waitlist(
    event_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    current_user: User = Depends(require_role(["admin", "planner", "viewer"])),
    db: AsyncSession = Depends(get_db),
):
    """
    Get paginated waitlist entries. Computes relative position for guests
    with `status=waiting` without rewriting the database.
    """
    items, total = await get_waitlists_for_event(
        event_id=event_id,
        tenant_id=current_user.tenant_id,
        db=db,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
    )

    return WaitlistListResponse(
        items=[WaitlistResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@waitlist_router.put(
    "/{waitlist_id}/status",
    response_model=WaitlistResponse,
    summary="Manually update waitlist status",
)
async def update_status_route(
    waitlist_id: uuid.UUID,
    data: WaitlistActionRequest,
    current_user: User = Depends(require_role(["admin", "planner"])),
    db: AsyncSession = Depends(get_db),
):
    """
    Allow planners to cancel or expire a waitlist entry.
    If an 'offered' entry is cancelled, it immediately promotes the next waiting guest.
    """
    result = await update_waitlist_status(
        waitlist_id=waitlist_id,
        tenant_id=current_user.tenant_id,
        new_status=data.status,
        db=db,
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Waitlist entry not found",
        )
    return WaitlistResponse.model_validate(result)
