"""
Analytics Schemas — Pydantic response models for the dashboard API.
"""

from datetime import datetime
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------


class RoomInventoryItem(BaseModel):
    """Single room type inventory status."""
    room_block_id: str
    room_type: str
    total_rooms: int
    booked_rooms: int
    held_rooms: int
    available: int
    waitlist_count: int
    utilization_pct: float
    negotiated_rate: float


# ---------------------------------------------------------------------------
# Guest Status
# ---------------------------------------------------------------------------


class GuestStatusBreakdown(BaseModel):
    """Aggregate guest booking status for the event."""
    total_invited: int
    confirmed: int
    held: int
    pending: int
    waitlisted: int
    cancelled: int


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


class BudgetOverview(BaseModel):
    """Corporate wallet aggregate for the event."""
    total_loaded: float
    total_spent: float
    remaining: float
    avg_per_booking: float
    projected_final_spend: float
    percentage_consumed: float
    confirmed_bookings: int


# ---------------------------------------------------------------------------
# Velocity
# ---------------------------------------------------------------------------


class VelocityDataPoint(BaseModel):
    """Single day in the booking velocity chart."""
    date: str
    count: int


# ---------------------------------------------------------------------------
# Stockout Prediction
# ---------------------------------------------------------------------------


class StockoutPrediction(BaseModel):
    """Per room type demand forecast."""
    room_type: str
    status: str  # "FULL" | "WARNING" | "ON_TRACK"
    utilization_pct: float
    daily_velocity: float
    projected_full_date: str | None
    days_until_full: int | None
    recommendation: str | None


# ---------------------------------------------------------------------------
# Category Demographics
# ---------------------------------------------------------------------------


class CategoryDemographic(BaseModel):
    """Booking rate per guest category."""
    category: str
    total_guests: int
    booked: int
    booking_rate_pct: float


# ---------------------------------------------------------------------------
# Recent Activity
# ---------------------------------------------------------------------------


class ActivityEntry(BaseModel):
    """Single entry in the live booking feed."""
    guest_name: str
    action: str
    room_type: str
    num_nights: int
    status: str
    timestamp: str | None


# ---------------------------------------------------------------------------
# Composite Responses
# ---------------------------------------------------------------------------


class AnalyticsOverviewResponse(BaseModel):
    """Full dashboard snapshot returned on initial page load."""
    inventory: list[RoomInventoryItem]
    guest_status: GuestStatusBreakdown
    budget: BudgetOverview
    recent_activity: list[ActivityEntry]


class AnalyticsForecastResponse(BaseModel):
    """Actionable intelligence: velocity + predictions + demographics."""
    velocity: list[VelocityDataPoint]
    predictions: list[StockoutPrediction]
    demographics: list[CategoryDemographic]
