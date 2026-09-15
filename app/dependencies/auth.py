from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import (
    AdminSessionDep,
    async_session_factory,
    reset_tenant_context,
    set_tenant_context,
)
from app.models.enums import UserRole
from app.models.user import User
from app.services.auth import get_current_user_from_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: AdminSessionDep,
) -> User:
    return await get_current_user_from_token(db, token)


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user",
        )
    return current_user


CurrentUser = Annotated[User, Depends(get_current_active_user)]


async def get_tenant_db(
    current_user: CurrentUser,
) -> AsyncGenerator[AsyncSession]:
    """Runtime session with RLS tenant context set from the authenticated user."""
    async with async_session_factory() as session:
        await set_tenant_context(session, str(current_user.tenant_id))
        try:
            yield session
        finally:
            await reset_tenant_context(session)


TenantSessionDep = Annotated[AsyncSession, Depends(get_tenant_db)]


class RequireRole:
    """Dependency that checks the current user has one of the allowed roles.

    Usage:
        required = RequireRole(UserRole.OWNER, UserRole.ADMIN)
        @router.get("/admin", dependencies=[Depends(required)])
    """

    def __init__(self, *allowed_roles: UserRole) -> None:
        self.allowed_roles = set(allowed_roles)

    def __call__(self, current_user: CurrentUser) -> User:
        if current_user.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user
