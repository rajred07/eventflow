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


class InviteMemberRequest(BaseModel):
    """Invite a new planner/viewer to join the current admin's tenant."""
    name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128, description="Initial password set by admin")
    role: str = Field(default="planner", pattern="^(planner|viewer)$", description="planner or viewer only — admins cannot be invited")


class UpdateMemberRequest(BaseModel):
    """Update a team member's role or active status."""
    role: str | None = Field(default=None, pattern="^(planner|viewer)$")
    is_active: bool | None = None


class UpdateProfileRequest(BaseModel):
    """Update the current user's own profile."""
    name: str | None = Field(default=None, min_length=2, max_length=255)
    email: EmailStr | None = None


class ChangePasswordRequest(BaseModel):
    """Change the current user's password."""
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)


class UpdateOrgRequest(BaseModel):
    """Update tenant/organization settings. Admin only."""
    name: str | None = Field(default=None, min_length=2, max_length=255)
    logo_url: str | None = Field(default=None, description="Public URL for org logo")
    description: str | None = None


class OrgResponse(BaseModel):
    """Organization details returned in account settings."""
    id: uuid.UUID
    name: str
    slug: str
    type: str
    description: str | None
    logo_url: str | None  # extracted from settings JSONB
    is_active: bool

    model_config = {"from_attributes": True}


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


class TeamMemberResponse(BaseModel):
    """A team member within the same tenant, returned in team list."""
    id: uuid.UUID
    name: str
    email: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
