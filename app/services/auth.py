import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from jwt.exceptions import InvalidTokenError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.tenant import get_tenant_by_id
from app.repositories.user import create_user, get_user_by_email, get_user_by_id
from app.security import (
    DUMMY_HASH,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

settings = get_settings()

REFRESH_TOKEN_PREFIX = "refresh_token:"


async def _issue_tokens(redis: Redis, user_id: str, tenant_id: str, role: str) -> dict:
    access_token = create_access_token(subject=user_id, tenant_id=tenant_id, role=role)
    refresh_token, jti = create_refresh_token(
        subject=user_id, tenant_id=tenant_id, role=role
    )
    ttl = settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400
    await redis.set(f"{REFRESH_TOKEN_PREFIX}{jti}", user_id, ex=ttl)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


async def create_viewer(
    db: AsyncSession, email: str, password: str, tenant_id: uuid.UUID
) -> User:
    email = email.lower()

    # Validate tenant exists and is active
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant or not tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )

    existing = await get_user_by_email(db, email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    hashed = hash_password(password)
    user = await create_user(
        db,
        email=email,
        hashed_password=hashed,
        tenant_id=tenant_id,
        role=UserRole.VIEWER,
    )
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate(
    db: AsyncSession, redis: Redis, username: str, password: str
) -> dict:
    email = username.lower()
    user = await get_user_by_email(db, email)
    if not user:
        verify_password(password, DUMMY_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user.last_login = datetime.now(UTC)
    await db.commit()
    return await _issue_tokens(
        redis, str(user.id), str(user.tenant_id), user.role.value
    )


async def refresh_tokens(db: AsyncSession, redis: Redis, token: str) -> dict:
    try:
        payload = decode_token(token, expected_type="refresh")
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    jti = payload["jti"]
    stored = await redis.getdel(f"{REFRESH_TOKEN_PREFIX}{jti}")
    if stored is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token revoked or expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload["sub"]
    try:
        user = await get_user_by_id(db, uuid.UUID(user_id))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Issue new token pair (token rotation) with fresh role from DB
    return await _issue_tokens(
        redis, str(user.id), str(user.tenant_id), user.role.value
    )


async def logout(redis: Redis, token: str) -> None:
    try:
        payload = decode_token(token, expected_type="refresh")
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    jti = payload["jti"]
    await redis.delete(f"{REFRESH_TOKEN_PREFIX}{jti}")


async def get_current_user_from_token(db: AsyncSession, token: str) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token, expected_type="access")
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        user = await get_user_by_id(db, uuid.UUID(user_id))
    except InvalidTokenError, ValueError:
        raise credentials_exception
    if user is None:
        raise credentials_exception
    return user
