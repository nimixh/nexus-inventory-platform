from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

settings = get_settings()

# Runtime engine — used by the app, connects as nexus_runtime (RLS enforced)
engine = create_async_engine(settings.RUNTIME_DATABASE_URL, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

# Admin engine — used for cross-tenant operations, connects as nexus (owner)
admin_engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
admin_session_factory = async_sessionmaker(admin_engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession]:
    """Basic runtime session (no tenant context). Used for unauthenticated routes."""
    async with async_session_factory() as session:
        yield session


async def get_admin_db() -> AsyncGenerator[AsyncSession]:
    """Admin session that bypasses RLS. Used for auth operations."""
    async with admin_session_factory() as session:
        yield session


async def set_tenant_context(session: AsyncSession, tenant_id: str) -> None:
    """Set the tenant context for RLS. Uses session-scoped (not transaction-local)."""
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :tid, false)"),
        {"tid": tenant_id},
    )


async def reset_tenant_context(session: AsyncSession) -> None:
    """Reset the tenant context to prevent cross-request leakage."""
    await session.execute(
        text("RESET app.current_tenant_id"),
    )


SessionDep = Annotated[AsyncSession, Depends(get_db)]
AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_db)]
