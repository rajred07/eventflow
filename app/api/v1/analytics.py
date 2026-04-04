"""
Analytics API — HTTP endpoints for dashboard data.

These endpoints serve the initial dashboard load (before WebSocket takes over)
and the forecast/prediction panels that are fetched on-demand.

Authentication:
    All endpoints require a valid JWT with admin/planner/viewer role.
    Tenant isolation is enforced via the user's tenant_id.
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.rbac import require_role
from app.db.session import get_db
from app.models.user import User

from app.core.analytics.engine import (
    get_booking_velocity,
    get_budget_overview,
    get_category_demographics,
    get_dashboard_snapshot,
    get_guest_status_breakdown,
    get_inventory_snapshot,
    get_recent_activity,
    get_stockout_prediction,
)

from app.schemas.analytics import (
    AnalyticsForecastResponse,
    AnalyticsOverviewResponse,
)

router = APIRouter(tags=["Analytics"])


# ---------------------------------------------------------------------------
# Dashboard Overview (initial page load)
# ---------------------------------------------------------------------------


@router.get(
    "/events/{event_id}/analytics/overview",
    response_model=AnalyticsOverviewResponse,
    summary="Dashboard Overview — inventory, budget, guests, activity",
)
async def analytics_overview(
    event_id: uuid.UUID,
    current_user: User = Depends(require_role(["admin", "planner", "viewer"])),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the complete dashboard snapshot:
    - Room inventory (all room types with booked/held/available/waitlist counts)
    - Guest status breakdown (confirmed/pending/waitlisted/cancelled)
    - Budget consumption overview (loaded/spent/remaining/projected)
    - Recent activity feed (last 10 booking lifecycle events)

    This is called once when the dashboard page loads. After loading,
    the WebSocket connection takes over for live updates.
    """
    snapshot = await get_dashboard_snapshot(event_id, current_user.tenant_id, db)

    # The snapshot includes 'type' and 'timestamp' keys for WS format.
    # The HTTP response model doesn't need those, so we return the inner data.
    return {
        "inventory": snapshot["inventory"],
        "guest_status": snapshot["guest_status"],
        "budget": snapshot["budget"],
        "recent_activity": snapshot["recent_activity"],
    }


# ---------------------------------------------------------------------------
# Forecast & Predictions (on-demand intelligence)
# ---------------------------------------------------------------------------


@router.get(
    "/events/{event_id}/analytics/forecast",
    response_model=AnalyticsForecastResponse,
    summary="Demand Forecast — velocity, stockout predictions, demographics",
)
async def analytics_forecast(
    event_id: uuid.UUID,
    current_user: User = Depends(require_role(["admin", "planner"])),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns actionable intelligence for the planner:
    - Booking velocity chart data (rooms booked per day, last 30 days)
    - Stockout predictions per room type (projected full date, status flags)
    - Category demographics (which guest categories are booking fastest)

    This powers the 'Deadline Pressure' panel and the velocity chart.
    """
    velocity = await get_booking_velocity(event_id, db)
    predictions = await get_stockout_prediction(event_id, db)
    demographics = await get_category_demographics(event_id, db)

    return {
        "velocity": velocity,
        "predictions": predictions,
        "demographics": demographics,
    }
