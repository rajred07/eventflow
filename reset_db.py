import asyncio
from app.db.session import engine
from app.models import Base
from redis.asyncio import Redis
from app.core.redis import pool

async def reset_database():
    print("🗑️  Dropping all tables from Postgres...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    print("✨ Recreating all tables in Postgres...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print("🧹 Flushing Redis Cache / Locks...")
    try:
        redis = Redis(connection_pool=pool)
        await redis.flushdb()
        await redis.aclose()
        print("✅ Redis flushed.")
    except Exception as e:
        print(f"⚠️ Redis flush skipped (is redis running?): {e}")

    print("🔌 Closing connections...")
    await engine.dispose()
    
    print("\n✅ Database reset complete! You can now safely rerun the test.")

if __name__ == "__main__":
    asyncio.run(reset_database())
