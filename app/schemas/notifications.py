"""
Notification Schemas — request/response models for notification endpoints.
"""

from pydantic import BaseModel


class ReminderBlastRequest(BaseModel):
    """Request body for the manual reminder blast endpoint."""
    categories: list[str]
    custom_message: str | None = None


class ReminderBlastResponse(BaseModel):
    """Response from the manual reminder blast endpoint."""
    queued: int
    categories: list[str]
    event_name: str
