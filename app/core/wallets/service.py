import uuid
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.wallet import Wallet, WalletTransaction
from app.models.guest import Guest

async def create_wallet(guest_id: uuid.UUID, event_id: uuid.UUID, tenant_id: uuid.UUID, initial_balance: Decimal, db: AsyncSession) -> Wallet:
    """Create a new wallet for a guest."""
    # Check if wallet already exists
    stmt = select(Wallet).where(Wallet.guest_id == guest_id)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Wallet already exists for this guest")

    wallet = Wallet(
        tenant_id=tenant_id,
        guest_id=guest_id,
        event_id=event_id,
        balance=initial_balance
    )
    db.add(wallet)
    await db.flush()

    if initial_balance > 0:
        tx = WalletTransaction(
            wallet_id=wallet.id,
            booking_id=None,
            type="credit",
            amount=initial_balance,
            description="Initial subsidy limit loaded"
        )
        db.add(tx)
        
    return wallet

async def load_subsidy(wallet_id: uuid.UUID, amount: Decimal, description: str, db: AsyncSession) -> Wallet:
    """Load additional funds into a wallet."""
    # Lock the wallet row
    stmt = select(Wallet).where(Wallet.id == wallet_id).with_for_update()
    result = await db.execute(stmt)
    wallet = result.scalar_one_or_none()
    
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    wallet.balance += amount
    
    tx = WalletTransaction(
        wallet_id=wallet.id,
        booking_id=None,
        type="credit",
        amount=amount,
        description=description
    )
    db.add(tx)
    
    return wallet

async def debit_on_booking(wallet_id: uuid.UUID, booking_id: uuid.UUID, amount: Decimal, db: AsyncSession) -> None:
    """Debit the wallet when a booking is confirmed. This must be called inside an active transaction."""
    if amount <= 0:
        return
        
    # We lock the wallet row to prevent concurrent race conditions on balance
    stmt = select(Wallet).where(Wallet.id == wallet_id).with_for_update()
    result = await db.execute(stmt)
    wallet = result.scalar_one_or_none()
    
    if not wallet:
        raise ValueError("Wallet not found")
        
    if wallet.balance < amount:
        raise ValueError("Insufficient wallet balance for this subsidy amount")
        
    wallet.balance -= amount
    
    tx = WalletTransaction(
        wallet_id=wallet.id,
        booking_id=booking_id,
        type="debit",
        amount=amount,
        description="Booking corporate subsidy applied"
    )
    db.add(tx)

async def credit_on_cancellation(wallet_id: uuid.UUID, booking_id: uuid.UUID, amount: Decimal, db: AsyncSession) -> None:
    """Credit the wallet when a booking is cancelled. Must be called inside an active transaction."""
    if amount <= 0:
        return
        
    stmt = select(Wallet).where(Wallet.id == wallet_id).with_for_update()
    result = await db.execute(stmt)
    wallet = result.scalar_one_or_none()
    
    if not wallet:
        raise ValueError("Wallet not found")
        
    wallet.balance += amount
    
    tx = WalletTransaction(
        wallet_id=wallet.id,
        booking_id=booking_id,
        type="credit",
        amount=amount,
        description="Booking cancellation refund"
    )
    db.add(tx)

async def get_wallet_with_history(guest_id: uuid.UUID, event_id: uuid.UUID, db: AsyncSession):
    """Retrieve wallet and transactions."""
    stmt = select(Wallet).where(Wallet.guest_id == guest_id, Wallet.event_id == event_id)
    result = await db.execute(stmt)
    wallet = result.scalar_one_or_none()
    
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
        
    tx_stmt = select(WalletTransaction).where(WalletTransaction.wallet_id == wallet.id).order_by(WalletTransaction.created_at.desc())
    tx_result = await db.execute(tx_stmt)
    transactions = tx_result.scalars().all()
    
    return {
        "id": wallet.id,
        "tenant_id": wallet.tenant_id,
        "guest_id": wallet.guest_id,
        "event_id": wallet.event_id,
        "balance": wallet.balance,
        "currency": wallet.currency,
        "created_at": wallet.created_at,
        "updated_at": wallet.updated_at,
        "transactions": transactions
    }

async def get_event_wallet_summary(event_id: uuid.UUID, tenant_id: uuid.UUID, db: AsyncSession):
    """Aggregate total loaded, spent across all wallets for the event."""
    stmt = select(
        func.count(Wallet.id).label("total_wallets"),
        func.sum(Wallet.balance).label("total_balance")
    ).where(Wallet.event_id == event_id, Wallet.tenant_id == tenant_id)
    
    result = await db.execute(stmt)
    row = result.first()
    
    total_wallets = row.total_wallets or 0
    total_balance = row.total_balance or Decimal('0.00')
    
    # Calculate spent (amount debited over all transactions)
    spent_stmt = select(func.sum(WalletTransaction.amount)).join(Wallet).where(
        Wallet.event_id == event_id,
        Wallet.tenant_id == tenant_id,
        WalletTransaction.type == "debit"
    )
    spent_result = await db.execute(spent_stmt)
    total_spent = spent_result.scalar_one_or_none() or Decimal('0.00')
    
    return {
        "event_id": event_id,
        "total_wallets": total_wallets,
        "total_balance": total_balance,
        "total_spent": total_spent
    }
