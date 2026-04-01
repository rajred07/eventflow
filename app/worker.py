"""
Celery Worker Configuration.

Initializes the Celery app using Redis as the message broker.
Connects task modules so Celery Beat can schedule them.
"""

from celery import Celery

from app.config import settings

celery_app = Celery(
    "eventflow",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks.inventory_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

# Celery Beat Schedule
celery_app.conf.beat_schedule = {
    "release-expired-holds-every-2-mins": {
        "task": "app.tasks.inventory_tasks.release_expired_holds_task",
        "schedule": 120.0,  # Every 2 minutes
    },
    "expire-waitlist-offers-hourly": {
        "task": "app.tasks.inventory_tasks.expire_waitlist_offers_task",
        "schedule": 3600.0, # Every 60 minutes
    },
}
