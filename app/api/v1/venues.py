"""
Venue Routes — listing and filtering venues.

Venues are global (not scoped to a tenant) — any authenticated user
can browse venues. NLP search is added in Phase 3.

GET  /api/v1/venues          → List venues with filters
GET  /api/v1/venues/{id}     → Get venue details
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.models.venue import Venue
from app.schemas.venue import VenueListResponse, VenueResponse

router = APIRouter(prefix="/venues", tags=["Venues"])


@router.get(
    "",
    response_model=VenueListResponse,
    summary="List venues with optional filters",
)
async def list_venues(
    city: str | None = Query(None, examples=["Goa"]),
    min_rooms: int | None = Query(None, ge=1),
    max_price: float | None = Query(None, ge=0),
    min_rating: float | None = Query(None, ge=0, le=5),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Browse available venues with optional filtering.
    Any authenticated user can search venues.
    """
    query = select(Venue).where(Venue.is_active == True)  # noqa: E712

    if city:
        query = query.where(Venue.city.ilike(f"%{city}%"))
    if min_rooms:
        query = query.where(Venue.total_rooms >= min_rooms)
    if min_rating:
        query = query.where(Venue.star_rating >= min_rating)

    # Count total matching venues
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginate
    query = query.order_by(Venue.star_rating.desc().nullslast())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    venues = list(result.scalars().all())

    return VenueListResponse(
        venues=[VenueResponse.model_validate(v) for v in venues],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{venue_id}",
    response_model=VenueResponse,
    summary="Get venue details",
)
async def get_venue(
    venue_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get full details for a specific venue."""
    result = await db.execute(
        select(Venue).where(Venue.id == venue_id, Venue.is_active == True)  # noqa: E712
    )
    venue = result.scalar_one_or_none()

    if venue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Venue not found",
        )
    return venue
