import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.rbac import require_role
from app.db.session import get_db
from app.models.user import User

from app.core.wallets.service import (
    get_event_wallet_summary,
    get_wallet_with_history,
    load_subsidy,
)
from app.schemas.wallet import (
    WalletEventSummary,
    WalletLoadRequest,
    WalletResponse,
    WalletWithHistoryResponse,
)

router = APIRouter(prefix="/events/{event_id}", tags=["Wallets"])

@router.get("/guests/{guest_id}/wallet", response_model=WalletWithHistoryResponse)
async def get_wallet_endpoint(
    event_id: uuid.UUID,
    guest_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(["admin", "planner", "viewer"])),
):
    """Get wallet balance and transaction history for a guest."""
    return await get_wallet_with_history(guest_id=guest_id, event_id=event_id, db=db)

@router.post("/guests/{guest_id}/wallet/load", response_model=WalletResponse)
async def load_subsidy_endpoint(
    event_id: uuid.UUID,
    guest_id: uuid.UUID,
    payload: WalletLoadRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(["admin", "planner"])),
):
    """Load an additional subsidy into a guest's wallet."""
    wallet_data = await get_wallet_with_history(guest_id=guest_id, event_id=event_id, db=db)
    
    wallet = await load_subsidy(
        wallet_id=wallet_data["id"],
        amount=payload.amount,
        description=payload.description,
        db=db
    )
    
    await db.commit()
    await db.refresh(wallet)
    return wallet

@router.get("/wallet-summary", response_model=WalletEventSummary)
async def event_wallet_summary_endpoint(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(["admin", "planner", "viewer"])),
):
    """Aggregate total wallet statistics for the event."""
    return await get_event_wallet_summary(event_id=event_id, tenant_id=current_user.tenant_id, db=db)
