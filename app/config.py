"""
Eventflow Configuration — loads .env into typed Python settings.

Usage:
    from app.config import settings
    print(settings.DATABASE_URL)
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://eventflow:eventflow123@localhost:5432/eventflow_db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT Auth
    JWT_SECRET: str = "eventflow-super-secret-key-change-in-production-2026"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    RESEND_API_KEY: str | None = None
    # FROM address for all outbound emails.
    # Without a verified Resend domain → use "onboarding@resend.dev" (works immediately).
    # Once you verify your domain on resend.com → change to "Eventflow <noreply@yourdomain.com>"
    RESEND_FROM_EMAIL: str = "Eventflow <onboarding@resend.dev>"
    # TEST MODE OVERRIDE: When set, ALL outbound emails are redirected to this single
    # address regardless of the guest's actual email. Keeps DB emails unique (satisfies
    # the unique constraint) while funneling everything to one inbox you can review.
    # Set to empty string "" to disable and use real recipient emails.
    RESEND_TEST_OVERRIDE_TO: str = ""

    # WhatsApp (Twilio) — Phase 8
    # If TWILIO_ACCOUNT_SID is None → mock mode (logs messages, doesn't send)
    TWILIO_ACCOUNT_SID: str | None = None
    TWILIO_AUTH_TOKEN: str | None = None
    TWILIO_WHATSAPP_FROM: str = "whatsapp:+14155238886"
    # TEST MODE: All WA messages redirect to this number (same pattern as RESEND_TEST_OVERRIDE_TO)
    TWILIO_TEST_OVERRIDE_TO: str = ""

    # App
    APP_NAME: str = "Eventflow"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }


# Singleton — import this everywhere
settings = Settings()
