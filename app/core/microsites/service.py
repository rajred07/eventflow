import uuid
from typing import List

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.event import Event
from app.models.guest import Guest
from app.models.microsite import Microsite
from app.models.room_block import RoomBlock
from app.models.room_block_allotment import RoomBlockAllotment
from app.schemas.microsite import MicrositeCreate, PublicEventDetailsResponse, PublicRoomOption, PublicRoomOptionsPayload

async def create_microsite(event_id: uuid.UUID, tenant_id: uuid.UUID, data: MicrositeCreate, db: AsyncSession) -> Microsite:
    # 1. Verify Event
    event_result = await db.execute(select(Event).where(Event.id == event_id, Event.tenant_id == tenant_id))
    event = event_result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # 2. Check if slug exists
    slug_result = await db.execute(select(Microsite).where(Microsite.slug == data.slug))
    if slug_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="URL slug is already taken.")
        
    # 3. Check if event already has a microsite
    existing_result = await db.execute(select(Microsite).where(Microsite.event_id == event_id))
    if existing_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Event already has a microsite configured.")

    microsite = Microsite(
        tenant_id=tenant_id,
        event_id=event_id,
        slug=data.slug,
        theme_color=data.theme_color,
        hero_image_url=data.hero_image_url,
        welcome_message=data.welcome_message,
        is_published=data.is_published
    )
    db.add(microsite)
    await db.commit()
    await db.refresh(microsite)
    return microsite

# ---------------------------------------------------------------------------
# Public Endpoints (Zero-Friction Magic Link)
# ---------------------------------------------------------------------------

async def _get_guest_and_event_by_token_and_slug(slug: str, guest_token: uuid.UUID, db: AsyncSession):
    """Helper: Validate the guest token and find the corresponding Event via slug."""
    # 1. Look up Microsite by slug
    m_result = await db.execute(select(Microsite).where(Microsite.slug == slug, Microsite.is_published == True))
    microsite = m_result.scalar_one_or_none()
    if not microsite:
        raise HTTPException(status_code=404, detail="Microsite not found or not published.")

    # 2. Look up Guest by token
    g_result = await db.execute(select(Guest).where(Guest.booking_token == guest_token, Guest.is_active == True))
    guest = g_result.scalar_one_or_none()
    if not guest:
        raise HTTPException(status_code=401, detail="Invalid or expired magic link token.")

    # 3. Security: Does this guest belong to the event attached to this microsite?
    if guest.event_id != microsite.event_id:
        raise HTTPException(status_code=403, detail="You are not invited to this event page.")

    # 4. Fetch the Event
    e_result = await db.execute(select(Event).where(Event.id == microsite.event_id))
    event = e_result.scalar_one()

    return guest, microsite, event


async def get_public_event_details(slug: str, guest_token: uuid.UUID, db: AsyncSession) -> PublicEventDetailsResponse:
    """Returns the visual payload and itinerary so the UI can construct the booking page."""
    guest, microsite, event = await _get_guest_and_event_by_token_and_slug(slug, guest_token, db)

    return PublicEventDetailsResponse(
        event_name=event.name,
        destination=event.destination,
        start_date=str(event.start_date),
        end_date=str(event.end_date),
        description=event.description,
        guest_name=guest.name,
        guest_category=guest.category,
        microsite_theme_color=microsite.theme_color,
        microsite_hero_image_url=microsite.hero_image_url,
        microsite_welcome_message=microsite.welcome_message
    )

async def get_public_available_rooms(slug: str, guest_token: uuid.UUID, db: AsyncSession) -> PublicRoomOptionsPayload:
    """
    Returns only the room blocks and dynamically calculated prices that this 
    guest is allowed to see, based on Event.category_rules.
    """
    guest, microsite, event = await _get_guest_and_event_by_token_and_slug(slug, guest_token, db)

    # Fetch all room block allotments for this event
    # To do this, we join RoomBlock and RoomBlockAllotment
    stmt = (
        select(RoomBlockAllotment, RoomBlock)
        .join(RoomBlock, RoomBlockAllotment.room_block_id == RoomBlock.id)
        .where(RoomBlock.event_id == event.id, RoomBlock.status == "confirmed")
    )
    result = await db.execute(stmt)
    rows = result.all()

    # Determine guest's constraints
    category_rules = event.category_rules or {}
    guest_rules = category_rules.get(guest.category, {})
    
    # Defaults in case the planner didn't specify rules
    allowed_types = guest_rules.get("allowed_room_types", [])
    subsidy_per_night = float(guest_rules.get("subsidy_per_night", 0.0))
    
    # In a real app we'd fetch the actual Wallet balance in case it was modified, 
    # but for Phase 2E scope we compute the baseline subsidy for the UI display:
    event_days = max(1, (event.end_date - event.start_date).days)
    total_corporate_subsidy = subsidy_per_night * event_days

    options: List[PublicRoomOption] = []
    
    for allotment, block in rows:
        # 1. Filtration Rule: Can the guest see this room?
        if allowed_types and allotment.room_type not in allowed_types:
            continue
            
        # 2. Availability Rule: Frontend needs current state
        available_rooms = allotment.total_rooms - (allotment.booked_rooms + allotment.held_rooms)
        
        # Room price calculation
        block_days = max(1, (block.check_out_date - block.check_in_date).days)
        base_total_cost = float(allotment.negotiated_rate) * block_days
        
        # 3. Negative Subsidy Rule (MAX 0)
        amount_due = max(0.0, base_total_cost - total_corporate_subsidy)
        
        options.append(PublicRoomOption(
            room_block_id=block.id,
            room_type=allotment.room_type,
            negotiated_rate=float(allotment.negotiated_rate),
            corporate_subsidy=total_corporate_subsidy,
            amount_due=amount_due,
            available_rooms=available_rooms
        ))
        
    return PublicRoomOptionsPayload(options=options)
