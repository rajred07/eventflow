"""
Database session management with async SQLAlchemy + connection pooling.

Key concepts:
- create_async_engine: Connection pool to PostgreSQL (reuses connections)
- async_sessionmaker: Factory that creates database sessions
- get_db(): FastAPI dependency that provides a session per request
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

# Connection pool — reuses connections instead of creating new ones per request
# pool_size=20: keep 20 connections alive
# max_overflow=10: allow 10 more during traffic spikes
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,  # Log SQL queries in debug mode
    pool_size=20,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,  # Refresh connections every 30 minutes
)

# Session factory — creates new sessions
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Don't expire objects after commit (avoids lazy load issues)
)


async def get_db() -> AsyncSession:
    """
    FastAPI dependency injection for database sessions.

    Usage in routes:
        @router.get("/events")
        async def list_events(db: AsyncSession = Depends(get_db)):
            ...

    The session is automatically closed after the request completes.
    """
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
