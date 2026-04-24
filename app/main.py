"""
Eventflow — Main FastAPI Application.

This is the entry point. It:
1. Creates the FastAPI app with metadata (for auto-generated docs)
2. Registers all API routers
3. Configures CORS (so the Next.js frontend can talk to the API)
4. Sets up database connection lifecycle
"""

from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.auth import router as auth_router
from app.api.v1.bookings import booking_router, event_booking_router, public_booking_router
from app.api.v1.events import router as events_router
from app.api.v1.guests import router as guests_router
from app.api.v1.room_blocks import blocks_router, event_blocks_router
from app.api.v1.venues import router as venues_router
from app.api.v1.waitlists import event_waitlist_router, waitlist_router
from app.api.v1.wallets import router as wallets_router
from app.api.v1.microsites import router as microsites_router
from app.api.v1.import_export import router as import_export_router
from app.api.v1.etl_import import router as etl_import_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.websockets import router as ws_router
from app.api.v1.analytics import router as analytics_router
from app.config import settings
from app.db.session import engine
from app.core.websockets.pubsub import start_pubsub_listener


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup and shutdown events.

    On startup: verify database connection.
    On shutdown: dispose connection pool cleanly.
    """
    # Startup — verify DB connection
    async with engine.begin() as conn:
        # Just test the connection
        await conn.execute(
            __import__("sqlalchemy").text("SELECT 1")
        )
    print(f"✅ {settings.APP_NAME} v{settings.APP_VERSION} started")
    print(f"📄 API Docs: http://localhost:8000/docs")

    # Phase 5: Start Redis Pub/Sub listener for real-time dashboard
    pubsub_task = asyncio.create_task(start_pubsub_listener())
    print(f"📡 Redis Pub/Sub listener started for live dashboard")

    yield  # App runs here

    # Shutdown — cancel Pub/Sub listener and clean up
    pubsub_task.cancel()
    try:
        await pubsub_task
    except asyncio.CancelledError:
        pass
    await engine.dispose()
    print("👋 Shutting down gracefully")


# Create the FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Multi-tenant Group Travel & Event Booking Infrastructure. "
        "Digitizes MICE events and destination weddings from venue discovery "
        "to final rooming list."
    ),
    lifespan=lifespan,
    docs_url="/docs",       # Swagger UI at /docs
    redoc_url="/redoc",     # ReDoc at /redoc
)

# CORS — allow Next.js frontend to make requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routers — all under /api/v1
app.include_router(auth_router, prefix="/api/v1")
app.include_router(events_router, prefix="/api/v1")
app.include_router(venues_router, prefix="/api/v1")
app.include_router(guests_router, prefix="/api/v1")
app.include_router(event_blocks_router, prefix="/api/v1")
app.include_router(blocks_router, prefix="/api/v1")
from app.api.v1.waitlists import event_waitlist_router, waitlist_router, public_waitlist_router
app.include_router(event_waitlist_router, prefix="/api/v1")
app.include_router(waitlist_router, prefix="/api/v1")
app.include_router(public_waitlist_router, prefix="/api/v1")
app.include_router(wallets_router, prefix="/api/v1")
app.include_router(microsites_router, prefix="/api/v1")
app.include_router(import_export_router, prefix="/api/v1")
app.include_router(etl_import_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")
app.include_router(public_booking_router, prefix="/api/v1")
app.include_router(event_booking_router, prefix="/api/v1")
app.include_router(booking_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")

# WebSocket router — no /api/v1 prefix (WS URLs are separate from REST)
app.include_router(ws_router)


# Health check — useful for Docker health checks and monitoring
@app.get("/health", tags=["System"])
async def health_check():
    """Simple health check endpoint."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }
