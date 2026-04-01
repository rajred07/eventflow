import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.rbac import require_role
from app.db.session import get_db
from app.models.user import User

from app.core.microsites.service import (
    create_microsite,
    get_public_available_rooms,
    get_public_event_details,
)
from app.schemas.microsite import (
    MicrositeCreate,
    MicrositeResponse,
    PublicEventDetailsResponse,
    PublicRoomOptionsPayload,
)

router = APIRouter(tags=["Microsites"])

# ---------------------------------------------------------------------------
# Planner API (Authenticated)
# ---------------------------------------------------------------------------

@router.post(
    "/events/{event_id}/microsite",
    response_model=MicrositeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create or configure the Event Microsite"
)
async def create_microsite_endpoint(
    event_id: uuid.UUID,
    data: MicrositeCreate,
    current_user: User = Depends(require_role(["admin", "planner"])),
    db: AsyncSession = Depends(get_db),
):
    """
    Creates the microsite configuration exposing the event slug.
    Only authorized planners can do this.
    """
    microsite = await create_microsite(
        event_id=event_id,
        tenant_id=current_user.tenant_id,
        data=data,
        db=db
    )
    return microsite

# ---------------------------------------------------------------------------
# Guest API (Unauthenticated, relies on Magic Link Booking Token)
# ---------------------------------------------------------------------------

@router.get(
    "/public/microsites/{slug}",
    response_model=PublicEventDetailsResponse,
    summary="Fetch Public Event Details (Zero Auth)"
)
async def public_microsite_details(
    slug: str,
    token: uuid.UUID = Query(..., description="Guest Booking Token"),
    db: AsyncSession = Depends(get_db),
):
    """
    Allows a guest to view the microsite's welcome page and event details.
    A valid booking token acts as their identity.
    """
    details = await get_public_event_details(slug=slug, guest_token=token, db=db)
    return details


@router.get(
    "/public/microsites/{slug}/rooms",
    response_model=PublicRoomOptionsPayload,
    summary="Fetch Filtered Room Options (Zero Auth)"
)
async def public_microsite_rooms(
    slug: str,
    token: uuid.UUID = Query(..., description="Guest Booking Token"),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns only the specific room blocks the guest is permitted to see,
    along with their exact out-of-pocket subsidized prices.
    Also returns real-time availability.
    """
    rooms = await get_public_available_rooms(slug=slug, guest_token=token, db=db)
    return rooms
