"""
Redis Connection Manager.

Sets up the async redis pool used for Layer 1 locking
(the 15-minute hold window).
"""

from typing import AsyncGenerator

from redis.asyncio import ConnectionPool, Redis

from app.config import settings

# Create a global connection pool
kwargs = {
    "decode_responses": True,
    "max_connections": 100,
}
if settings.REDIS_URL.startswith("rediss://"):
    kwargs["ssl_cert_reqs"] = "none"

pool = ConnectionPool.from_url(
    settings.REDIS_URL,
    **kwargs
)

async def get_redis() -> AsyncGenerator[Redis, None]:
    """Dependency injection for FastAPI routes."""
    client = Redis(connection_pool=pool)
    try:
        yield client
    finally:
        await client.aclose()
