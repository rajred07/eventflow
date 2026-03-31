"""
Tenant Middleware — sets PostgreSQL Row-Level Security context.

On every authenticated request, this sets the tenant_id in the
PostgreSQL session so that RLS policies automatically filter data.

How it works:
1. get_current_user() gives us the user (with tenant_id)
2. We run SET app.tenant_id = '<tenant_uuid>' on the DB session
3. PostgreSQL RLS policies use current_setting('app.tenant_id') to filter
4. Every SELECT/INSERT/UPDATE/DELETE on tenant-scoped tables is auto-filtered

This means even if our Python code forgets a WHERE clause,
the database itself blocks cross-tenant data access.
"""

import uuid

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.middleware.auth import get_current_user
from app.models.user import User


async def get_tenant_db(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncSession:
    """
    FastAPI dependency that provides a database session with
    tenant context set for Row-Level Security.

    Usage in routes:
        async def my_route(
            current_user: User = Depends(get_current_user),
            db: AsyncSession = Depends(get_tenant_db),
        ):
            # All queries on this db session are auto-filtered by tenant_id
            events = await db.execute(select(Event))  # Only this tenant's events!
    """
    # Set the tenant context in PostgreSQL session
    await db.execute(
        text("SET app.tenant_id = :tenant_id"),
        {"tenant_id": str(current_user.tenant_id)},
    )
    return db


def get_tenant_id(current_user: User = Depends(get_current_user)) -> uuid.UUID:
    """
    Simple dependency to get just the tenant_id from the current user.

    Usage:
        async def my_route(tenant_id: UUID = Depends(get_tenant_id)):
            ...
    """
    return current_user.tenant_id
