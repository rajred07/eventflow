"""
Models package — import all models here so Alembic can discover them.

When Alembic runs migrations, it imports this file, which imports
all models, which registers all tables with the Base metadata.
"""

from app.db.base import Base
from app.models.event import Event
from app.models.guest import Guest
from app.models.room_block import RoomBlock
from app.models.room_block_allotment import RoomBlockAllotment
from app.models.tenant import Tenant
from app.models.user import User
from app.models.venue import Venue
from app.models.waitlist import Waitlist
from app.models.booking import Booking

__all__ = [
    "Base", "Tenant", "User", "Event", "Venue", "Guest",
    "RoomBlock", "RoomBlockAllotment", "Waitlist", "Booking",
]
