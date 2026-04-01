"""
Room Block Routes — endpoints for managing event inventory contracts.

POST   /api/v1/events/{event_id}/room-blocks     → Create block + allotments
GET    /api/v1/events/{event_id}/room-blocks     → List blocks for event
GET    /api/v1/room-blocks/{block_id}            → Get block details
PUT    /api/v1/room-blocks/{block_id}            → Update basic info
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.rbac import require_role
from app.core.room_blocks.service import (
    create_room_block,
    get_room_block_by_id,
    get_room_blocks_for_event,
    update_room_block,
)
from app.db.session import get_db
from app.models.user import User
from app.schemas.room_block import (
    RoomBlockCreate,
    RoomBlockListResponse,
    RoomBlockResponse,
    RoomBlockUpdate,
)

# Route for creating blocks (tied to event)
event_blocks_router = APIRouter(prefix="/events/{event_id}/room-blocks", tags=["Room Blocks"])

# Route for managing existing blocks directly by ID
blocks_router = APIRouter(prefix="/room-blocks", tags=["Room Blocks"])


@event_blocks_router.post(
    "",
    response_model=RoomBlockResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a room block with allotments",
)
async def create_block_route(
    event_id: uuid.UUID,
    data: RoomBlockCreate,
    current_user: User = Depends(require_role(["admin", "planner"])),
    db: AsyncSession = Depends(get_db),
):
    """
    Creates a new room block linking an event to a venue, initializing 
    separate allotment rows for each room type provided.
    
    In Phase 2, blocks are created natively as "confirmed".
    """
    try:
        block = await create_room_block(
            data=data,
            tenant_id=current_user.tenant_id,
            event_id=event_id,
            db=db,
        )
        return block
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@event_blocks_router.get(
    "",
    response_model=RoomBlockListResponse,
    summary="List all room blocks for an event",
)
async def list_event_blocks(
    event_id: uuid.UUID,
    current_user: User = Depends(require_role(["admin", "planner", "viewer"])),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all room blocks and their detailed allotments (inventory) for a given event.
    """
    try:
        blocks = await get_room_blocks_for_event(
            event_id=event_id,
            tenant_id=current_user.tenant_id,
            db=db,
        )
        # SQLAlchemy models to Pydantic validation
        return RoomBlockListResponse(
            blocks=[RoomBlockResponse.model_validate(b) for b in blocks],
            total=len(blocks)
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@blocks_router.get(
    "/{block_id}",
    response_model=RoomBlockResponse,
    summary="Get room block details",
)
async def get_block(
    block_id: uuid.UUID,
    current_user: User = Depends(require_role(["admin", "planner", "viewer"])),
    db: AsyncSession = Depends(get_db),
):
    """Get details and allotments for a single room block."""
    block = await get_room_block_by_id(block_id, current_user.tenant_id, db)
    if block is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room block not found",
        )
    return block


@blocks_router.put(
    "/{block_id}",
    response_model=RoomBlockResponse,
    summary="Update room block metadata",
)
async def update_block_route(
    block_id: uuid.UUID,
    data: RoomBlockUpdate,
    current_user: User = Depends(require_role(["admin", "planner"])),
    db: AsyncSession = Depends(get_db),
):
    """
    Partial update for block metadata (dates, deadline, notes).
    Allotment inventory adjustments are handled via specific inventory endpoints.
    """
    try:
        block = await update_room_block(
            block_id=block_id,
            data=data,
            tenant_id=current_user.tenant_id,
            db=db,
        )
        if block is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Room block not found",
            )
        return block
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
