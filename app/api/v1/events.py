"""
Event Routes — CRUD operations for events.

POST   /api/v1/events          → Create a new event
GET    /api/v1/events          → List events (paginated, filtered)
GET    /api/v1/events/{id}     → Get event details
PUT    /api/v1/events/{id}     → Update event
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.rbac import require_role
from app.core.events.service import (
    create_event,
    get_event_by_id,
    get_events,
    update_event,
)
from app.db.session import get_db
from app.models.user import User
from app.schemas.event import (
    EventCreate,
    EventListResponse,
    EventResponse,
    EventUpdate,
)

router = APIRouter(prefix="/events", tags=["Events"])


@router.post(
    "",
    response_model=EventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new event",
)
async def create_event_route(
    data: EventCreate,
    current_user: User = Depends(require_role(["admin", "planner"])),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new MICE event or wedding.

    Only admin and planner roles can create events.
    The event is automatically scoped to the current user's tenant.
    """
    event = await create_event(
        data=data,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        db=db,
    )
    return event


@router.get(
    "",
    response_model=EventListResponse,
    summary="List events for current tenant",
)
async def list_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    type_filter: str | None = Query(None, alias="type"),
    current_user: User = Depends(require_role(["admin", "planner", "viewer"])),
    db: AsyncSession = Depends(get_db),
):
    """
    Get paginated list of events for the current tenant.
    Supports filtering by status and type.
    """
    events, total = await get_events(
        tenant_id=current_user.tenant_id,
        db=db,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        type_filter=type_filter,
    )

    return EventListResponse(
        events=[EventResponse.model_validate(e) for e in events],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{event_id}",
    response_model=EventResponse,
    summary="Get event details",
)
async def get_event(
    event_id: uuid.UUID,
    current_user: User = Depends(require_role(["admin", "planner", "viewer"])),
    db: AsyncSession = Depends(get_db),
):
    """Get a single event by ID."""
    event = await get_event_by_id(event_id, current_user.tenant_id, db)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )
    return event


@router.put(
    "/{event_id}",
    response_model=EventResponse,
    summary="Update an event",
)
async def update_event_route(
    event_id: uuid.UUID,
    data: EventUpdate,
    current_user: User = Depends(require_role(["admin", "planner"])),
    db: AsyncSession = Depends(get_db),
):
    """
    Update an event. Only provided fields are changed.
    Only admin and planner roles can update events.
    """
    event = await update_event(event_id, data, current_user.tenant_id, db)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )
    return event
