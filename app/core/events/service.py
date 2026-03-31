"""
Event Service — business logic for event CRUD operations.

Separated from the API layer so that:
1. Routes only handle HTTP (request/response)
2. Business logic lives here (validation, DB operations)
3. Same logic can be called from tests, CLI, or background tasks
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.schemas.event import EventCreate, EventUpdate


async def create_event(
    data: EventCreate,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> Event:
    """Create a new event for the given tenant."""
    event = Event(
        tenant_id=tenant_id,
        created_by=user_id,
        name=data.name,
        type=data.type,
        description=data.description,
        destination=data.destination,
        start_date=data.start_date,
        end_date=data.end_date,
        expected_guests=data.expected_guests,
        category_rules=data.category_rules or {},
        extra_data=data.extra_data or {},
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


async def get_events(
    tenant_id: uuid.UUID,
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    status_filter: str | None = None,
    type_filter: str | None = None,
) -> tuple[list[Event], int]:
    """
    Get paginated events for a tenant with optional filters.
    Returns (events, total_count).
    """
    query = select(Event).where(Event.tenant_id == tenant_id)

    if status_filter:
        query = query.where(Event.status == status_filter)
    if type_filter:
        query = query.where(Event.type == type_filter)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Get paginated results
    query = query.order_by(Event.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    events = list(result.scalars().all())

    return events, total


async def get_event_by_id(
    event_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> Event | None:
    """Get a single event by ID, scoped to the tenant."""
    result = await db.execute(
        select(Event).where(Event.id == event_id, Event.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


async def update_event(
    event_id: uuid.UUID,
    data: EventUpdate,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> Event | None:
    """Update an event. Only updates fields that are provided (not None)."""
    event = await get_event_by_id(event_id, tenant_id, db)
    if event is None:
        return None

    # Only update fields that were explicitly set
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(event, field, value)

    await db.commit()
    await db.refresh(event)
    return event
