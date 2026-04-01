"""
Guest Routes — CRUD operations for guest management.

POST   /api/v1/events/{event_id}/guests          → Add single guest
POST   /api/v1/events/{event_id}/guests/bulk     → Bulk import
GET    /api/v1/events/{event_id}/guests          → List guests (paginated)
GET    /api/v1/events/{event_id}/guests/{id}     → Get guest details
PUT    /api/v1/events/{event_id}/guests/{id}     → Update guest
DELETE /api/v1/events/{event_id}/guests/{id}     → Deactivate guest
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.rbac import require_role
from app.core.guests.service import (
    bulk_create_guests,
    create_guest,
    deactivate_guest,
    get_guest_by_id,
    get_guests,
    update_guest,
)
from app.db.session import get_db
from app.models.user import User
from app.schemas.guest import (
    GuestBulkCreate,
    GuestBulkCreateResponse,
    GuestCreate,
    GuestListResponse,
    GuestResponse,
    GuestUpdate,
)

router = APIRouter(prefix="/events/{event_id}/guests", tags=["Guests"])


@router.post(
    "",
    response_model=GuestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a single guest to an event",
)
async def create_guest_route(
    event_id: uuid.UUID,
    data: GuestCreate,
    current_user: User = Depends(require_role(["admin", "planner"])),
    db: AsyncSession = Depends(get_db),
):
    """
    Add a single guest to the event matching the current user's tenant.
    Guest email must be unique within the event.
    """
    try:
        guest = await create_guest(
            data=data,
            tenant_id=current_user.tenant_id,
            event_id=event_id,
            db=db,
        )
        return guest
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post(
    "/bulk",
    response_model=GuestBulkCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Bulk import guests",
)
async def bulk_create_guests_route(
    event_id: uuid.UUID,
    data: GuestBulkCreate,
    current_user: User = Depends(require_role(["admin", "planner"])),
    db: AsyncSession = Depends(get_db),
):
    """
    Import up to 500 guests in a single pass.
    Errors on individual rows (e.g. duplicate email) will skip that row and
    report the error, but the rest of the batch will succeed.
    """
    try:
        result = await bulk_create_guests(
            data=data,
            tenant_id=current_user.tenant_id,
            event_id=event_id,
            db=db,
        )
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "",
    response_model=GuestListResponse,
    summary="List guests for an event",
)
async def list_guests(
    event_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category_filter: str | None = Query(None, alias="category"),
    active_only: bool = Query(True, description="Filter out deactivated guests"),
    current_user: User = Depends(require_role(["admin", "planner", "viewer"])),
    db: AsyncSession = Depends(get_db),
):
    """
    Get paginated list of guests for an event.
    You can optionally filter by category or include inactive (soft-deleted) guests.
    """
    guests, total = await get_guests(
        event_id=event_id,
        tenant_id=current_user.tenant_id,
        db=db,
        page=page,
        page_size=page_size,
        category_filter=category_filter,
        active_only=active_only,
    )

    return GuestListResponse(
        guests=[GuestResponse.model_validate(g) for g in guests],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{guest_id}",
    response_model=GuestResponse,
    summary="Get guest details",
)
async def get_guest(
    event_id: uuid.UUID,
    guest_id: uuid.UUID,
    current_user: User = Depends(require_role(["admin", "planner", "viewer"])),
    db: AsyncSession = Depends(get_db),
):
    """Get details for a single guest."""
    guest = await get_guest_by_id(
        guest_id=guest_id,
        event_id=event_id,
        tenant_id=current_user.tenant_id,
        db=db,
    )
    if guest is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Guest not found",
        )
    return guest


@router.put(
    "/{guest_id}",
    response_model=GuestResponse,
    summary="Update guest",
)
async def update_guest_route(
    event_id: uuid.UUID,
    guest_id: uuid.UUID,
    data: GuestUpdate,
    current_user: User = Depends(require_role(["admin", "planner"])),
    db: AsyncSession = Depends(get_db),
):
    """Partial update of a guest. Only provided fields change."""
    try:
        guest = await update_guest(
            guest_id=guest_id,
            data=data,
            event_id=event_id,
            tenant_id=current_user.tenant_id,
            db=db,
        )
        if guest is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Guest not found",
            )
        return guest
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete(
    "/{guest_id}",
    response_model=GuestResponse,
    summary="Deactivate guest",
)
async def delete_guest_route(
    event_id: uuid.UUID,
    guest_id: uuid.UUID,
    current_user: User = Depends(require_role(["admin", "planner"])),
    db: AsyncSession = Depends(get_db),
):
    """
    Soft-delete a guest. Their booking token stops working,
    but their historical data stays in the system.
    """
    guest = await deactivate_guest(
        guest_id=guest_id,
        event_id=event_id,
        tenant_id=current_user.tenant_id,
        db=db,
    )
    if guest is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Guest not found",
        )
    return guest
