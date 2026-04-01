"""
Waitlist Service — manages event waitlists.

Implements the pattern: No hard-coded `position` column. Position is calculated 
dynamically using COUNT(*) WHERE added_at < this.added_at. This avoids 
expensive O(N) cascades when someone is promoted or cancelled.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guest import Guest
from app.models.room_block import RoomBlock
from app.models.waitlist import Waitlist
from app.schemas.waitlist import WaitlistCreate


async def _verify_event_ownership(
    event_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    from app.models.event import Event

    result = await db.execute(
        select(Event.id).where(Event.id == event_id, Event.tenant_id == tenant_id)
    )
    if result.scalar_one_or_none() is None:
        raise ValueError("Event not found or not accessible.")


def _get_position_query(waitlist_alias):
    """
    Returns a scalar subquery that calculates position for a specific row.
    Position = (number of waiting people added before this person) + 1.
    If the person is not "waiting", returns null.
    """
    sub_w = select(func.count(Waitlist.id) + 1).where(
        Waitlist.room_block_id == waitlist_alias.room_block_id,
        Waitlist.room_type == waitlist_alias.room_type,
        Waitlist.status == "waiting",
        Waitlist.created_at < waitlist_alias.created_at,
    ).scalar_subquery()
    return sub_w


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


async def add_to_waitlist(
    data: WaitlistCreate,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    db: AsyncSession,
) -> Waitlist:
    """
    Add a guest to the waitlist for a specific block and room type.
    """
    await _verify_event_ownership(event_id, tenant_id, db)

    # Fast validation: does guest exist?
    guest = await db.execute(select(Guest.id).where(Guest.id == data.guest_id))
    if not guest.scalar_one_or_none():
        raise ValueError("Guest not found.")

    # Does block exist?
    block = await db.execute(
        select(RoomBlock.id).where(RoomBlock.id == data.room_block_id)
    )
    if not block.scalar_one_or_none():
        raise ValueError("Room block not found.")

    # Check if they are already on the waitlist for this room type
    existing = await db.execute(
        select(Waitlist.id).where(
            Waitlist.guest_id == data.guest_id,
            Waitlist.room_block_id == data.room_block_id,
            Waitlist.room_type == data.room_type,
            Waitlist.status.in_(["waiting", "offered"]),
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("Guest is already on the waitlist or holds an offer for this room.")

    waitlist_entry = Waitlist(
        tenant_id=tenant_id,
        event_id=event_id,
        guest_id=data.guest_id,
        room_block_id=data.room_block_id,
        room_type=data.room_type,
        status="waiting",
    )
    db.add(waitlist_entry)
    await db.commit()
    await db.refresh(waitlist_entry)

    # To return with dynamic position attached, we inject it manually
    # by counting the DB, but just returning the object directly works 
    # since we'll wrap it in get_waitlist_by_id logic or let the endpoint do it.
    return waitlist_entry


# ---------------------------------------------------------------------------
# Dynamic Query Read
# ---------------------------------------------------------------------------


async def get_waitlists_for_event(
    event_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    status_filter: str | None = None,
) -> tuple[list[dict], int]:
    """
    Get paginated waitlist entries for a specific event.
    Because we need a computed 'position', we return a list of dicts or tuples
    that map to WaitlistResponse.
    """
    query = select(Waitlist).where(
        Waitlist.event_id == event_id, Waitlist.tenant_id == tenant_id
    )

    if status_filter:
        query = query.where(Waitlist.status == status_filter)

    # Total count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginate and order by oldest first (highest priority if status=waiting)
    query = query.order_by(Waitlist.created_at.asc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    # For the actual results, we also need the computed position.
    pos_subquery = _get_position_query(Waitlist)
    query_with_pos = select(Waitlist, pos_subquery.label("computed_position")).where(
        Waitlist.event_id == event_id, Waitlist.tenant_id == tenant_id
    )
    
    if status_filter:
        query_with_pos = query_with_pos.where(Waitlist.status == status_filter)

    query_with_pos = query_with_pos.order_by(Waitlist.created_at.asc())
    query_with_pos = query_with_pos.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query_with_pos)
    
    merged_results = []
    for waitlist_obj, computed_pos in result.all():
        data = {
            "id": waitlist_obj.id,
            "tenant_id": waitlist_obj.tenant_id,
            "event_id": waitlist_obj.event_id,
            "guest_id": waitlist_obj.guest_id,
            "room_block_id": waitlist_obj.room_block_id,
            "room_type": waitlist_obj.room_type,
            "status": waitlist_obj.status,
            "offer_expires_at": waitlist_obj.offer_expires_at,
            "created_at": waitlist_obj.created_at,
            "updated_at": waitlist_obj.updated_at,
            "position": computed_pos if waitlist_obj.status == "waiting" else None,
        }
        merged_results.append(data)

    return merged_results, total


async def get_waitlist_by_id(
    waitlist_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> dict | None:
    """Get single waitlist entry with computed position."""
    pos_subquery = _get_position_query(Waitlist)
    query = select(Waitlist, pos_subquery.label("computed_position")).where(
        Waitlist.id == waitlist_id, Waitlist.tenant_id == tenant_id
    )

    result = await db.execute(query)
    row = result.first()
    if not row:
        return None

    w_obj, computed_pos = row
    return {
        "id": w_obj.id,
        "tenant_id": w_obj.tenant_id,
        "event_id": w_obj.event_id,
        "guest_id": w_obj.guest_id,
        "room_block_id": w_obj.room_block_id,
        "room_type": w_obj.room_type,
        "status": w_obj.status,
        "offer_expires_at": w_obj.offer_expires_at,
        "created_at": w_obj.created_at,
        "updated_at": w_obj.updated_at,
        "position": computed_pos if w_obj.status == "waiting" else None,
    }


# ---------------------------------------------------------------------------
# State Transitions (Promote, Cancel, Expire)
# ---------------------------------------------------------------------------


async def promote_next(
    room_block_id: uuid.UUID,
    room_type: str,
    db: AsyncSession,
) -> Waitlist | None:
    """
    Called by the Booking Engine when a CONFIRMED booking is cancelled,
    or an EXPIRED hold is released.

    Finds the oldest "waiting" person in this block/type and offers them the room.
    Because we don't store hard-coded positions, we just pick the one with 
    the smallest `created_at`.
    """
    result = await db.execute(
        select(Waitlist)
        .where(
            Waitlist.room_block_id == room_block_id,
            Waitlist.room_type == room_type,
            Waitlist.status == "waiting",
        )
        .order_by(Waitlist.created_at.asc())
        .limit(1)
        # We lock specifically this row so it isn't double-promoted by background tasks
        .with_for_update(skip_locked=True)
    )

    next_in_line = result.scalar_one_or_none()
    if next_in_line:
        next_in_line.status = "offered"
        next_in_line.offer_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        await db.commit()
        await db.refresh(next_in_line)
        # In a real system, trigger Celery task to email the guest here.
    
    return next_in_line


async def update_waitlist_status(
    waitlist_id: uuid.UUID,
    tenant_id: uuid.UUID,
    new_status: str,
    db: AsyncSession,
) -> dict | None:
    """
    Manually update a waitlist status (e.g. planner cancels a guest's slot).
    If a guest is cancelled while they hold an 'offered' status, this
    could immediately promote the *next* person.
    """
    w = await db.execute(
        select(Waitlist).where(
            Waitlist.id == waitlist_id, Waitlist.tenant_id == tenant_id
        )
    )
    waitlist_entry = w.scalar_one_or_none()
    if not waitlist_entry:
        return None

    old_status = waitlist_entry.status
    waitlist_entry.status = new_status
    if new_status != "offered":
        waitlist_entry.offer_expires_at = None

    await db.commit()

    # If the planner cancelled an ACTIVE offer, we should immediately promote the next person
    if old_status == "offered" and new_status == "cancelled":
        await promote_next(waitlist_entry.room_block_id, waitlist_entry.room_type, db)

    return await get_waitlist_by_id(waitlist_id, tenant_id, db)


async def accept_waitlist_offer(
    waitlist_id: uuid.UUID,
    db: AsyncSession,
) -> Waitlist:
    """
    Called when a guest accepts a waitlist offer within their 24hr window.
    This effectively converts their status from 'offered' to 'converted'.
    The frontend should immediately redirect them to the booking/hold process.
    """
    w_result = await db.execute(select(Waitlist).where(Waitlist.id == waitlist_id))
    waitlist = w_result.scalar_one_or_none()
    
    if not waitlist:
        raise ValueError("Waitlist entry not found.")
        
    if waitlist.status != "offered":
        raise ValueError(f"Invalid waitlist status to accept: {waitlist.status}")

    # Validate 24hr expiry
    if waitlist.offer_expires_at and waitlist.offer_expires_at < datetime.now(timezone.utc):
        waitlist.status = "expired"
        await db.commit()
        # Cascade promote to the NEXT person
        await promote_next(waitlist.room_block_id, waitlist.room_type, db)
        raise ValueError("This waitlist offer has expired.")

    waitlist.status = "converted"
    await db.commit()
    await db.refresh(waitlist)

    return waitlist
