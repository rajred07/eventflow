import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.rbac import require_role
from app.db.session import get_db
from app.models.user import User

from app.core.exports.service import generate_rooming_list_csv

router = APIRouter(tags=["Exports"])

@router.get(
    "/events/{event_id}/rooming-list",
    summary="Export Hotel Rooming List CSV",
    response_description="A CSV file containing the finalized rooming list."
)
async def export_rooming_list(
    event_id: uuid.UUID,
    room_type: Optional[str] = Query(None, description="Filter by specific room type"),
    status_filter: str = Query("CONFIRMED", description="Defaults to confirmed bookings only"),
    current_user: User = Depends(require_role(["admin", "planner"])),
    db: AsyncSession = Depends(get_db),
):
    """
    Called by Planners to download their event headcount instantly.
    Spits out a clean, PMS-ready CSV containing all guest, dates, and finalized balance data.
    """
    try:
        csv_data = await generate_rooming_list_csv(
            event_id=event_id,
            tenant_id=current_user.tenant_id,
            db=db,
            room_type=room_type,
            status_filter=status_filter
        )
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}\n\n{error_details}")
    
    # We yield the string in chunks to support standard StreamingResponse
    def iter_csv():
        yield csv_data

    headers = {
        "Content-Disposition": f"attachment; filename=rooming-list-{event_id}.csv"
    }
    return StreamingResponse(iter_csv(), media_type="text/csv", headers=headers)
