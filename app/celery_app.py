import os
from celery import Celery
from celery.schedules import crontab
from datetime import timedelta

# Default to the local redis container if no URL is provided
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Initialize the Celery application
app = Celery(
    "eventflow",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.tasks.email_tasks", "app.tasks.cron_tasks", "app.tasks.inventory_tasks"]
)

# Celery settings
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # In production with thousands of tasks, it's good practice to set rate limits
    # task_default_rate_limit='100/m'
)

# Configure Periodic Tasks (Celery Beat)
app.conf.beat_schedule = {
    # 1. Hold Expiry Cleanup (Every 2 minutes)
    "hold-expiry-cleanup": {
        "task": "app.tasks.cron_tasks.hold_expiry_cleanup",
        "schedule": timedelta(minutes=2),
    },
    # 2. Waitlist Offer Expiry (Every hour)
    "waitlist-offer-expiry": {
        "task": "app.tasks.cron_tasks.waitlist_offer_expiry",
        "schedule": crontab(minute=0), # Top of every hour
    },
    # 3. Booking Reminder Sequence (Daily at 9 AM)
    "booking-reminder-sequence": {
        "task": "app.tasks.cron_tasks.booking_reminder_sequence",
        "schedule": crontab(hour=9, minute=0),
    },
    # 4. Event Auto-Completion (Daily at 8 AM)
    "event-auto-completion": {
        "task": "app.tasks.cron_tasks.event_auto_completion",
        "schedule": crontab(hour=8, minute=0),
    },
}
