"""
Room Block Service — handles block creation and allotment logic.

Ensures that allotments are properly created as child records and scoped
to the tenant and event.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.room_block import RoomBlock
from app.models.room_block_allotment import RoomBlockAllotment
from app.schemas.room_block import (
    RoomBlockCreate,
    RoomBlockUpdate,
)


async def _verify_event_ownership(
    event_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """Verify event belongs to tenant."""
    from app.models.event import Event

    result = await db.execute(
        select(Event).where(Event.id == event_id, Event.tenant_id == tenant_id)
    )
    if result.scalar_one_or_none() is None:
        raise ValueError(f"Event {event_id} not found or not accessible.")


async def _verify_venue_exists(venue_id: uuid.UUID, db: AsyncSession) -> None:
    """Verify venue exists (venues are global, no tenant check needed)."""
    from app.models.venue import Venue

    result = await db.execute(
        select(Venue.id).where(Venue.id == venue_id, Venue.is_active == True)  # noqa: E712
    )
    if result.scalar_one_or_none() is None:
        raise ValueError(f"Venue {venue_id} not found or inactive.")


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


async def create_room_block(
    data: RoomBlockCreate,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    db: AsyncSession,
) -> RoomBlock:
    """
    Create a room block and its child allotments.
    """
    await _verify_event_ownership(event_id, tenant_id, db)
    await _verify_venue_exists(data.venue_id, db)

    # 1. Check for duplicate room types in payload
    provided_types = [a.room_type for a in data.allotments]
    if len(provided_types) != len(set(provided_types)):
        raise ValueError("Duplicate room types provided in allotments array")

    # 2. Prevent creating multiple blocks for the same event+venue (simplification)
    existing_block = await db.execute(
        select(RoomBlock.id).where(
            RoomBlock.event_id == event_id, RoomBlock.venue_id == data.venue_id
        )
    )
    if existing_block.scalar_one_or_none():
        raise ValueError(
            "A room block already exists for this event and venue. Update it instead."
        )

    # 3. Create the block
    block = RoomBlock(
        tenant_id=tenant_id,
        event_id=event_id,
        venue_id=data.venue_id,
        status="confirmed",  # Phase 2 assumption
        check_in_date=data.check_in_date,
        check_out_date=data.check_out_date,
        hold_deadline=data.hold_deadline,
        notes=data.notes,
    )
    db.add(block)
    await db.flush()  # Gets block.id

    # 4. Create the allotments (separate rows)
    for allotment_data in data.allotments:
        allotment = RoomBlockAllotment(
            room_block_id=block.id,
            room_type=allotment_data.room_type,
            total_rooms=allotment_data.total_rooms,
            negotiated_rate=allotment_data.negotiated_rate,
        )
        db.add(allotment)

    await db.commit()

    # Re-fetch with relationships loaded
    result = await db.execute(
        select(RoomBlock)
        .options(selectinload(RoomBlock.allotments))
        .where(RoomBlock.id == block.id)
    )
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


async def get_room_blocks_for_event(
    event_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> list[RoomBlock]:
    """Get all room blocks and their allotments for an event."""
    result = await db.execute(
        select(RoomBlock)
        .options(selectinload(RoomBlock.allotments))
        .where(RoomBlock.event_id == event_id, RoomBlock.tenant_id == tenant_id)
        .order_by(RoomBlock.created_at.desc())
    )
    return list(result.scalars().all())


async def get_room_block_by_id(
    block_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> RoomBlock | None:
    """Get block details by ID."""
    result = await db.execute(
        select(RoomBlock)
        .options(selectinload(RoomBlock.allotments))
        .where(RoomBlock.id == block_id, RoomBlock.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


async def update_room_block(
    block_id: uuid.UUID,
    data: RoomBlockUpdate,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> RoomBlock | None:
    """
    Update main block details.
    Does not update allotments — that requires a separate focused endpoint
    because changing inventory impacts live bookings.
    """
    block = await get_room_block_by_id(block_id, tenant_id, db)
    if not block:
        return None

    update_data = data.model_dump(exclude_unset=True)
    
    # Specific validation for dates if changing
    new_in = update_data.get("check_in_date", block.check_in_date)
    new_out = update_data.get("check_out_date", block.check_out_date)
    if new_out <= new_in:
        raise ValueError("check_out_date must be after check_in_date")

    for field, value in update_data.items():
        setattr(block, field, value)

    await db.commit()
    await db.refresh(block)
    return block


# (Phase 2 constraint: We won't build complicated update_allotment logic yet 
# to keep the surface area small. If planners need more rooms, they can add them 
# via a separate future endpoint, but reducing rooms requires complex checks 
# against current bookings.)
