import csv
import io
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.booking import Booking
from app.models.event import Event
from app.models.guest import Guest
from app.models.room_block import RoomBlock
from app.models.room_block_allotment import RoomBlockAllotment
from app.models.wallet import Wallet

async def generate_rooming_list_csv(
    event_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
    room_type: Optional[str] = None,
    status_filter: str = "CONFIRMED"
) -> str:
    """
    Generates a pure CSV string for the Event's rooming list.
    Filtered by status (defaulting to CONFIRMED).
    Can be filtered by specific room_types for large hotels.
    """
    # Verify event
    e_result = await db.execute(select(Event).where(Event.id == event_id, Event.tenant_id == tenant_id))
    event = e_result.scalar_one_or_none()
    if not event:
        raise ValueError("Event not found")
        
    stmt = (
        select(Booking)
        .options(
            selectinload(Booking.guest),
            selectinload(Booking.guest).selectinload(Guest.wallet),
            selectinload(Booking.room_block),
            selectinload(Booking.allotment)
        )
        .where(
            Booking.event_id == event_id,
            Booking.tenant_id == tenant_id,
            Booking.status == status_filter
        )
    )
    
    if room_type:
        stmt = stmt.where(Booking.room_type == room_type)
        
    # Sort logically by Room Type then Guest Name
    stmt = stmt.order_by(Booking.room_type.asc())
        
    result = await db.execute(stmt)
    bookings = result.scalars().all()

    # Pre-fetch wallets for accurate subsidy data mapping
    # since Wallet tracking handles exactly how much was offset
    # SQLAlchemy eagerly loaded it, but we extract the correct one.
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Headers aligned to Hotel standard PMS needs
    writer.writerow([
        "Guest Name",
        "Email",
        "Phone",
        "Category",
        "Room Type",
        "Check-in",
        "Check-out",
        "Nights",
        "Rate Per Night",
        "Total Cost",
        "Subsidy Applied",
        "Guest Pays",
        "Special Requests"
    ])
    
    for b in bookings:
        guest = b.guest
        
        # Calculate nights
        in_date = b.room_block.check_in_date
        out_date = b.room_block.check_out_date
        nights = max(1, (out_date - in_date).days)
        
        rate = float(b.allotment.negotiated_rate)
        total_cost = rate * nights
        
        subsidy_applied = float(b.subsidy_applied) if b.subsidy_applied else 0.0
        guest_pays = max(0.0, total_cost - subsidy_applied)
        
        writer.writerow([
            guest.name,
            guest.email,
            guest.phone or "N/A",
            guest.category,
            b.room_type.title(),
            str(in_date),
            str(out_date),
            nights,
            f"{rate:.2f}",
            f"{total_cost:.2f}",
            f"{subsidy_applied:.2f}",
            f"{guest_pays:.2f}",
            b.special_requests or "None"
        ])
        
    return output.getvalue()
