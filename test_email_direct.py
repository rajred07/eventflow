"""
Test the email task directly with the latest confirmed booking ID.
"""
import os
os.environ["DATABASE_URL"] = "postgresql+asyncpg://neondb_owner:npg_K4sSycNaZk2o@ep-snowy-fog-aomuz29t-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?ssl=require"
os.environ["REDIS_URL"] = "rediss://default:AYEzAAIjcDE1MWQ4MTMxYWY2YTA0OGVmYmZkZjc0YzRmOWZmZjM0OXAxMA@dynamic-kid-87295.upstash.io:6379"

# Import and run the task directly (NOT via .delay()) to catch any exception
from app.tasks.email_tasks import send_booking_confirmation_email

# The latest confirmed booking ID from the database
BOOKING_ID = "488a7d3c-770d-481d-a111-4124a34c83bc"

print(f"Running send_booking_confirmation_email for booking {BOOKING_ID}...")
try:
    # Call the underlying function directly (bypass Celery)
    send_booking_confirmation_email(BOOKING_ID)
    print("✅ Email task completed successfully!")
except Exception as e:
    import traceback
    print(f"❌ Email task FAILED: {e}")
    traceback.print_exc()
