"""
Redis Connection Manager.

Sets up the async redis pool used for Layer 1 locking
(the 15-minute hold window).
"""

from typing import AsyncGenerator

from redis.asyncio import ConnectionPool, Redis

from app.config import settings

# Strip the CERT_NONE string which crashes redis.asyncio but might be in the env var for Celery
redis_url = settings.REDIS_URL
if "?ssl_cert_reqs=CERT_NONE" in redis_url:
    redis_url = redis_url.replace("?ssl_cert_reqs=CERT_NONE", "")

# Create a global connection pool
kwargs = {
    "decode_responses": True,
    "max_connections": 100,
}
if redis_url.startswith("rediss://"):
    kwargs["ssl_cert_reqs"] = "none"

pool = ConnectionPool.from_url(
    redis_url,
    **kwargs
)

async def get_redis() -> AsyncGenerator[Redis, None]:
    """Dependency injection for FastAPI routes."""
    client = Redis(connection_pool=pool)
    try:
        yield client
    finally:
        await client.aclose()
