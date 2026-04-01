"""
Eventflow — Main FastAPI Application.

This is the entry point. It:
1. Creates the FastAPI app with metadata (for auto-generated docs)
2. Registers all API routers
3. Configures CORS (so the Next.js frontend can talk to the API)
4. Sets up database connection lifecycle
"""

from contextlib import asynccontextmanager

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
from app.config import settings
from app.db.session import engine


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

    yield  # App runs here

    # Shutdown — clean up connection pool
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
    allow_origins=[
        "http://localhost:3000",   # Next.js dev server
        "http://127.0.0.1:3000",
    ],
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
app.include_router(event_waitlist_router, prefix="/api/v1")
app.include_router(waitlist_router, prefix="/api/v1")
app.include_router(wallets_router, prefix="/api/v1")
app.include_router(microsites_router, prefix="/api/v1")
app.include_router(public_booking_router, prefix="/api/v1")
app.include_router(event_booking_router, prefix="/api/v1")
app.include_router(booking_router, prefix="/api/v1")


# Health check — useful for Docker health checks and monitoring
@app.get("/health", tags=["System"])
async def health_check():
    """Simple health check endpoint."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }
