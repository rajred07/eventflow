"""
WebSocket API — Real-Time Planner Dashboard.

Endpoint:
    WS /ws/events/{event_id}/dashboard?token={jwt_token}

Authentication:
    Browsers cannot send Authorization headers during the WebSocket
    handshake, so the JWT is passed as a query parameter.

    On connect:
        1. Extract ?token= from query string
        2. Decode and verify JWT signature
        3. Extract tenant_id from the JWT payload
        4. Verify event.tenant_id == planner's tenant_id
        5. Reject with 4003 if any check fails
        6. Push initial_snapshot immediately
        7. Keep connection alive — all future updates via Redis Pub/Sub

Security:
    Without step 4, any authenticated user could connect to ANY event's
    dashboard and see live booking data they don't own. The tenant check
    prevents cross-tenant data leakage.
"""

import uuid
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.auth.service import decode_token
from app.core.websockets.manager import manager
from app.core.analytics.engine import get_dashboard_snapshot
from app.db.session import async_session

from sqlalchemy import select, text
from app.models.event import Event

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])


async def _authenticate_ws(
    websocket: WebSocket,
    event_id: uuid.UUID,
    token: str,
) -> uuid.UUID | None:
    """
    Validate the JWT token and verify tenant ownership of the event.
    Returns the tenant_id if valid, None if authentication fails.
    """
    # 1. Decode JWT
    payload = decode_token(token)
    if payload is None:
        logger.warning(f"WS auth failed: invalid/expired token for event {event_id}")
        return None

    # 2. Must be an access token
    if payload.get("type") != "access":
        logger.warning(f"WS auth failed: not an access token for event {event_id}")
        return None

    # 3. Extract tenant_id from token
    tenant_id_str = payload.get("tenant_id")
    if not tenant_id_str:
        logger.warning(f"WS auth failed: no tenant_id in token for event {event_id}")
        return None

    try:
        token_tenant_id = uuid.UUID(tenant_id_str)
    except ValueError:
        logger.warning(f"WS auth failed: invalid tenant_id format in token")
        return None

    # 4. Verify the event belongs to this tenant
    async with async_session() as db:
        await db.execute(text("SET app.bypass_rls = 'on'"))
        result = await db.execute(
            select(Event.tenant_id).where(Event.id == event_id)
        )
        event_row = result.first()

        if event_row is None:
            logger.warning(f"WS auth failed: event {event_id} not found")
            return None

        if event_row.tenant_id != token_tenant_id:
            logger.warning(
                f"WS auth failed: tenant mismatch — "
                f"token={token_tenant_id}, event={event_row.tenant_id}"
            )
            return None

    return token_tenant_id


@router.websocket("/ws/events/{event_id}/dashboard")
async def dashboard_websocket(
    websocket: WebSocket,
    event_id: uuid.UUID,
):
    """
    Real-time planner dashboard WebSocket.

    Flow:
        1. Authenticate via JWT query param
        2. Verify tenant owns this event
        3. Push initial_snapshot (full dashboard state)
        4. Keep alive — live updates arrive via Redis Pub/Sub → ConnectionManager
    """
    # ── Extract token from query params manually ──────────────────────────
    # FastAPI's Query() doesn't work reliably with WebSocket endpoints.
    token = websocket.query_params.get("token")
    if not token:
        # Must accept before we can send a close frame with a custom code
        await websocket.accept()
        await websocket.close(code=4003, reason="Missing token query parameter")
        return

    # ── Step 1: Authenticate ──────────────────────────────────────────────
    tenant_id = await _authenticate_ws(websocket, event_id, token)
    if tenant_id is None:
        await websocket.accept()
        await websocket.close(code=4003, reason="Forbidden: authentication failed")
        return

    # ── Step 2: Register connection (this also calls websocket.accept()) ──
    await manager.connect(event_id, websocket)

    try:
        # ── Step 3: Push initial snapshot ─────────────────────────────────
        async with async_session() as db:
            await db.execute(text("SET app.bypass_rls = 'on'"))
            snapshot = await get_dashboard_snapshot(event_id, tenant_id, db)

        await manager.send_personal(websocket, snapshot)
        logger.info(f"WS initial_snapshot sent for event {event_id}")

        # ── Step 4: Keep alive ────────────────────────────────────────────
        # The connection stays open. All live updates arrive via the
        # Redis Pub/Sub listener → ConnectionManager.broadcast().
        # We just need to keep the WebSocket alive by receiving pings
        # or client messages (which we ignore).
        while True:
            # Wait for any message from client (heartbeat, ping, etc.)
            # If the client disconnects, this raises WebSocketDisconnect.
            await websocket.receive_text()

    except WebSocketDisconnect:
        logger.info(f"WS client disconnected from event {event_id}")
    except Exception as e:
        logger.error(f"WS error for event {event_id}: {e}")
    finally:
        manager.disconnect(event_id, websocket)

