"""
Inventory Background Tasks.

These are Celery tasks triggered by Celery Beat to automatically 
process waitlist queues and expired temporary room holds.
Since Celery is synchronous, we use `async-to-sync` patterns 
to call our async database services.
"""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.waitlists.service import promote_next
from app.db.session import async_session_maker
from app.models.booking import Booking
from app.models.room_block_allotment import RoomBlockAllotment
from app.models.waitlist import Waitlist
from app.worker import celery_app

logger = logging.getLogger(__name__)


async def _async_release_expired_holds() -> int:
    """Async logic to release holds older than now."""
    released_count = 0
    now = datetime.now(timezone.utc)
    
    async with async_session_maker() as db:
        # 1. Find bookings with status="HELD" and hold_expires_at < now
        result = await db.execute(
            select(Booking).where(
                Booking.status == "HELD",
                Booking.hold_expires_at <= now,
            )
        )
        expired_bookings = result.scalars().all()

        for booking in expired_bookings:
            try:
                # 2. Lock the allotment row
                allotment_result = await db.execute(
                    select(RoomBlockAllotment)
                    .where(RoomBlockAllotment.id == booking.allotment_id)
                    .with_for_update()
                )
                allotment = allotment_result.scalar_one()

                # 3. Release the hold
                if allotment.held_rooms > 0:
                    allotment.held_rooms -= 1
                
                booking.status = "EXPIRED"
                
                await db.commit()
                released_count += 1
                
                logger.info(f"Released expired hold {booking.id} for {booking.room_type}")

                # 4. Trigger the waitlist loop
                await promote_next(booking.room_block_id, booking.room_type, db)
                
            except Exception as e:
                await db.rollback()
                logger.error(f"Failed to release hold {booking.id}: {str(e)}")

    return released_count


@celery_app.task
def release_expired_holds_task():
    """Celery entry point to run the async expiration sweep."""
    logger.info("Starting expired hold sweep...")
    released = asyncio.run(_async_release_expired_holds())
    logger.info(f"Sweep complete. Released {released} holds.")
    return released


async def _async_expire_waitlist_offers() -> int:
    """Async logic to expire unaccepted waitlist offers."""
    expired_count = 0
    now = datetime.now(timezone.utc)
    
    async with async_session_maker() as db:
        # Find all Waitlist entries where they were offered a room but took >24h
        result = await db.execute(
            select(Waitlist).where(
                Waitlist.status == "offered",
                Waitlist.offer_expires_at <= now,
            )
        )
        expired_offers = result.scalars().all()

        for offer in expired_offers:
            try:
                offer.status = "expired"
                await db.commit()
                expired_count += 1
                
                logger.info(f"Waitlist offer {offer.id} expired.")
                
                # Cascade: Someone else might still be waiting
                await promote_next(offer.room_block_id, offer.room_type, db)
                
            except Exception as e:
                await db.rollback()
                logger.error(f"Failed to expire waitlist offer {offer.id}: {str(e)}")

    return expired_count


@celery_app.task
def expire_waitlist_offers_task():
    """Celery entry point for waitlist offer sweeps."""
    logger.info("Starting waitlist offer expiration sweep...")
    expired = asyncio.run(_async_expire_waitlist_offers())
    logger.info(f"Sweep complete. Expired {expired} offers.")
    return expired
