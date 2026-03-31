"""
Auth Schemas — request/response models for authentication endpoints.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    """Register a new tenant + admin user in one step."""

    # Tenant info
    tenant_name: str = Field(..., min_length=2, max_length=255, examples=["Acme Corp"])
    tenant_type: str = Field(
        default="corporate",
        pattern="^(corporate|wedding_planner|agency)$",
        examples=["corporate"],
    )

    # User info
    name: str = Field(..., min_length=2, max_length=255, examples=["Rahul Sharma"])
    email: EmailStr = Field(..., examples=["rahul@acme.com"])
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    """Login with email and password."""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """JWT token pair returned on login/register."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    """Request a new access token using a refresh token."""

    refresh_token: str


class UserResponse(BaseModel):
    """User data returned in API responses."""

    id: uuid.UUID
    email: str
    name: str
    role: str
    tenant_id: uuid.UUID
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
