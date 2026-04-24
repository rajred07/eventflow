"""
Auth Routes — registration, login, and token refresh.

POST /api/v1/auth/register  → Create tenant + admin user
POST /api/v1/auth/login     → Get JWT access + refresh tokens
POST /api/v1/auth/refresh   → Get new access token using refresh token
GET  /api/v1/auth/me        → Get current user info
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.service import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.middleware.auth import get_current_user
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    InviteMemberRequest,
    LoginRequest,
    OrgResponse,
    RefreshRequest,
    RegisterRequest,
    TeamMemberResponse,
    TokenResponse,
    UpdateMemberRequest,
    UpdateOrgRequest,
    UpdateProfileRequest,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _slugify(name: str) -> str:
    """Convert a name like 'Acme Corp' to 'acme-corp'."""
    return name.lower().strip().replace(" ", "-")


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new tenant and admin user",
)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """
    Creates a new tenant organization and its first admin user.
    Returns JWT tokens for immediate login.
    """
    from sqlalchemy import text
    await db.execute(text("SET app.bypass_rls = 'on'"))
    
    # Check if email already exists
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Check if tenant slug already exists
    slug = _slugify(data.tenant_name)
    existing_tenant = await db.execute(select(Tenant).where(Tenant.slug == slug))
    if existing_tenant.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Organization name already taken",
        )

    # Create tenant
    tenant = Tenant(
        name=data.tenant_name,
        slug=slug,
        type=data.tenant_type,
    )
    db.add(tenant)
    await db.flush()  # Flush to get tenant.id before creating user

    # Create admin user
    user = User(
        tenant_id=tenant.id,
        email=data.email,
        name=data.name,
        password_hash=hash_password(data.password),
        role="admin",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Generate tokens
    token_data = {
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "role": user.role,
    }

    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login with email and password",
)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate user and return JWT tokens."""
    from sqlalchemy import text
    await db.execute(text("SET app.bypass_rls = 'on'"))

    # Find user by email
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    # Generate tokens
    token_data = {
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "role": user.role,
    }

    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
)
async def refresh_token(data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Get a new access token using a valid refresh token."""
    payload = decode_token(data.refresh_token)

    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    from sqlalchemy import text
    await db.execute(text("SET app.bypass_rls = 'on'"))

    # Verify user still exists and is active
    import uuid

    user_id = uuid.UUID(payload["sub"])
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
        )

    # Generate new token pair
    token_data = {
        "sub": str(user.id),
        "tenant_id": str(user.tenant_id),
        "role": user.role,
    }

    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user info",
)
async def get_me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user's details."""
    return current_user


# ---------------------------------------------------------------------------
# Team Management — Admin only: invite, list, update, deactivate
# ---------------------------------------------------------------------------


@router.post(
    "/invite-member",
    response_model=TeamMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a new planner or viewer to your team",
)
async def invite_member(
    data: InviteMemberRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Admin-only. Creates a new user under the SAME tenant as the current admin.
    The new user can be a planner or viewer — not an admin.
    No email sent — admin shares the credentials out-of-band.
    """
    from sqlalchemy import text
    await db.execute(text("SET app.bypass_rls = 'on'"))

    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can invite team members",
        )

    # Email must be globally unique
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email '{data.email}' is already registered",
        )

    new_user = User(
        tenant_id=current_user.tenant_id,      # Same tenant — key line
        email=data.email,
        name=data.name,
        password_hash=hash_password(data.password),
        role=data.role,                         # "planner" or "viewer" only
        is_active=True,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user


@router.get(
    "/team",
    response_model=list[TeamMemberResponse],
    summary="List all team members in your tenant",
)
async def list_team(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns all users within the same tenant as the requesting user.
    Accessible by admin, planner, or viewer — all can see who’s on the team.
    """
    from sqlalchemy import text
    await db.execute(text("SET app.bypass_rls = 'on'"))

    result = await db.execute(
        select(User)
        .where(User.tenant_id == current_user.tenant_id)
        .order_by(User.created_at.asc())
    )
    return result.scalars().all()


@router.put(
    "/team/{user_id}",
    response_model=TeamMemberResponse,
    summary="Update a team member's role or active status",
)
async def update_team_member(
    user_id: uuid.UUID,
    data: UpdateMemberRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin only. Change a team member's role or reactivate them."""
    from sqlalchemy import text
    await db.execute(text("SET app.bypass_rls = 'on'"))

    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admins only")

    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == current_user.tenant_id)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="User not found in your tenant")

    if member.id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot modify your own account here")

    if data.role is not None:
        member.role = data.role
    if data.is_active is not None:
        member.is_active = data.is_active

    await db.commit()
    await db.refresh(member)
    return member


@router.delete(
    "/team/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate a team member",
)
async def deactivate_team_member(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin only. Soft-deactivates a user — they can no longer log in."""
    from sqlalchemy import text
    await db.execute(text("SET app.bypass_rls = 'on'"))

    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admins only")

    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == current_user.tenant_id)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="User not found in your tenant")

    if member.id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot deactivate yourself")

    member.is_active = False
    await db.commit()


# ---------------------------------------------------------------------------
# Account Settings — profile, password, org settings
# ---------------------------------------------------------------------------


@router.patch(
    "/me",
    response_model=UserResponse,
    summary="Update current user's profile (name / email)",
)
async def update_profile(
    data: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Any logged-in user can update their own name and email."""
    from sqlalchemy import text
    await db.execute(text("SET app.bypass_rls = 'on'"))

    if data.email and data.email != current_user.email:
        # Check global uniqueness
        clash = await db.execute(select(User).where(User.email == data.email))
        if clash.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Email '{data.email}' is already in use",
            )
        current_user.email = data.email

    if data.name:
        current_user.name = data.name

    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.post(
    "/change-password",
    status_code=status.HTTP_200_OK,
    summary="Change current user's password",
)
async def change_password(
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Verify the current password then store a new hash."""
    from sqlalchemy import text
    await db.execute(text("SET app.bypass_rls = 'on'"))

    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    current_user.password_hash = hash_password(data.new_password)
    await db.commit()
    return {"message": "Password updated successfully"}


@router.get(
    "/tenant",
    response_model=OrgResponse,
    summary="Get current tenant / organization info",
)
async def get_tenant(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the org details for the current user's tenant."""
    from sqlalchemy import text
    await db.execute(text("SET app.bypass_rls = 'on'"))

    result = await db.execute(
        select(Tenant).where(Tenant.id == current_user.tenant_id)
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Extract logo_url from settings JSONB (no migration needed)
    logo_url = (tenant.settings or {}).get("logo_url")
    return OrgResponse(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        type=tenant.type,
        description=tenant.description,
        logo_url=logo_url,
        is_active=tenant.is_active,
    )


@router.patch(
    "/tenant",
    response_model=OrgResponse,
    summary="Update organization name, logo, description (Admin only)",
)
async def update_tenant(
    data: UpdateOrgRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin-only. Update tenant branding/info stored in the settings JSONB."""
    from sqlalchemy import text
    await db.execute(text("SET app.bypass_rls = 'on'"))

    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admins only")

    result = await db.execute(
        select(Tenant).where(Tenant.id == current_user.tenant_id)
    )
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if data.name:
        tenant.name = data.name
    if data.description is not None:
        tenant.description = data.description
    if data.logo_url is not None:
        settings = dict(tenant.settings or {})
        settings["logo_url"] = data.logo_url
        tenant.settings = settings

    await db.commit()

    logo_url = (tenant.settings or {}).get("logo_url")
    return OrgResponse(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        type=tenant.type,
        description=tenant.description,
        logo_url=logo_url,
        is_active=tenant.is_active,
    )
