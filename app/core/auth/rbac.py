"""
RBAC — Role-Based Access Control.

Defines what each role can do. Used as a FastAPI dependency
to check permissions before executing route handlers.

Usage:
    @router.post("/events")
    async def create_event(
        current_user: User = Depends(require_role(["admin", "planner"]))
    ):
        ...
"""

from fastapi import Depends, HTTPException, status

from app.middleware.auth import get_current_user
from app.models.user import User

# Permission matrix — which roles can do what
ROLE_PERMISSIONS = {
    "admin": [
        "create_event",
        "manage_event",
        "manage_blocks",
        "view_dashboard",
        "manage_wallet",
        "import_guests",
        "manage_guests",
        "export_rooming_list",
        "manage_users",
    ],
    "planner": [
        "create_event",
        "manage_event",
        "manage_blocks",
        "view_dashboard",
        "import_guests",
        "manage_guests",
        "export_rooming_list",
    ],
    "viewer": [
        "view_dashboard",
        "export_rooming_list",
    ],
    "hotel_admin": [
        "manage_blocks",
        "view_dashboard",
        "export_rooming_list",
    ],
}


def require_role(allowed_roles: list[str]):
    """
    FastAPI dependency that checks if the current user has one of the allowed roles.

    Returns the current user if authorized, raises 403 if not.
    """

    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' does not have permission. "
                f"Required: {allowed_roles}",
            )
        return current_user

    return role_checker


def require_permission(permission: str):
    """
    FastAPI dependency that checks if the current user has a specific permission.

    More granular than require_role — checks the permission matrix.
    """

    async def permission_checker(
        current_user: User = Depends(get_current_user),
    ) -> User:
        user_permissions = ROLE_PERMISSIONS.get(current_user.role, [])
        if permission not in user_permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission}' not granted to role '{current_user.role}'",
            )
        return current_user

    return permission_checker
