"""
Models package — import all models here so Alembic can discover them.

When Alembic runs migrations, it imports this file, which imports
all models, which registers all tables with the Base metadata.
"""

from app.db.base import Base
from app.models.event import Event
from app.models.tenant import Tenant
from app.models.user import User
from app.models.venue import Venue

__all__ = ["Base", "Tenant", "User", "Event", "Venue"]
