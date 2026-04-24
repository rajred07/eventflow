import asyncio
import os
os.environ["DATABASE_URL"] = "postgresql+asyncpg://neondb_owner:npg_K4sSycNaZk2o@ep-snowy-fog-aomuz29t-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?ssl=require"

from sqlalchemy import text
from app.db.session import async_session

async def run():
    async with async_session() as db:
        print("=== NOTIFICATION LOGS (last 10) ===")
        res = await db.execute(text(
            "SELECT type, status, recipient_email, error_message, sent_at "
            "FROM notification_logs ORDER BY sent_at DESC LIMIT 10"
        ))
        rows = res.fetchall()
        if rows:
            for r in rows:
                print(r)
        else:
            print("NO NOTIFICATION LOGS FOUND")

        print("\n=== CONFIRMED BOOKINGS (last 5) ===")
        res2 = await db.execute(text(
            "SELECT id, status, guest_id, created_at FROM bookings "
            "WHERE status = 'CONFIRMED' ORDER BY created_at DESC LIMIT 5"
        ))
        for r in res2.fetchall():
            print(r)

asyncio.run(run())
