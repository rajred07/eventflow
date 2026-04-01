from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

class WalletTransactionResponse(BaseModel):
    id: UUID
    wallet_id: UUID
    booking_id: Optional[UUID]
    type: str
    amount: Decimal
    description: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

class WalletResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    guest_id: UUID
    event_id: UUID
    balance: Decimal
    currency: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class WalletWithHistoryResponse(WalletResponse):
    transactions: List[WalletTransactionResponse] = []

class WalletLoadRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, description="Amount to load into the wallet")
    description: str = Field(..., description="Reason for loading the subsidy")

class WalletEventSummary(BaseModel):
    event_id: UUID
    total_wallets: int
    total_balance: Decimal
    total_spent: Decimal

    class Config:
        from_attributes = True
