"""Tests for Row-Level Security enforcement at the database level."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

OWNER_URL = "postgresql+psycopg://nexus:nexus@127.0.0.1:5432/nexus_test"
RUNTIME_URL = (
    "postgresql+psycopg://nexus_runtime:nexus_runtime@127.0.0.1:5432/nexus_test"
)


@pytest.fixture(scope="module")
def owner_engine():
    return create_async_engine(OWNER_URL, pool_pre_ping=True)


@pytest.fixture(scope="module")
def runtime_engine():
    return create_async_engine(RUNTIME_URL, pool_pre_ping=True)


@pytest.fixture
async def owner_session(owner_engine):
    factory = async_sessionmaker(owner_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
async def runtime_session(runtime_engine):
    factory = async_sessionmaker(runtime_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
async def two_tenants(owner_session: AsyncSession):
    """Create two tenants and one user each using the owner role (bypasses RLS)."""
    tenant_a_id = uuid.uuid4()
    tenant_b_id = uuid.uuid4()
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()

    await owner_session.execute(
        text(
            "INSERT INTO tenants "
            "(id, name, subscription_plan, subscription_status, is_active) "
            "VALUES (:id, :name, 'starter', 'active', true)"
        ),
        {"id": tenant_a_id, "name": f"Tenant-A-{tenant_a_id.hex[:8]}"},
    )
    await owner_session.execute(
        text(
            "INSERT INTO tenants "
            "(id, name, subscription_plan, subscription_status, is_active) "
            "VALUES (:id, :name, 'starter', 'active', true)"
        ),
        {"id": tenant_b_id, "name": f"Tenant-B-{tenant_b_id.hex[:8]}"},
    )
    await owner_session.execute(
        text(
            "INSERT INTO users "
            "(id, tenant_id, email, role, hashed_password, is_active) "
            "VALUES (:id, :tid, :email, 'owner', 'fakehash', true)"
        ),
        {
            "id": user_a_id,
            "tid": tenant_a_id,
            "email": f"a-{user_a_id.hex[:8]}@test.com",
        },
    )
    await owner_session.execute(
        text(
            "INSERT INTO users "
            "(id, tenant_id, email, role, hashed_password, is_active) "
            "VALUES (:id, :tid, :email, 'viewer', 'fakehash', true)"
        ),
        {
            "id": user_b_id,
            "tid": tenant_b_id,
            "email": f"b-{user_b_id.hex[:8]}@test.com",
        },
    )
    await owner_session.commit()

    yield {
        "tenant_a": tenant_a_id,
        "tenant_b": tenant_b_id,
        "user_a": user_a_id,
        "user_b": user_b_id,
    }

    # Cleanup
    await owner_session.execute(
        text("DELETE FROM users WHERE id IN (:a, :b)"),
        {"a": user_a_id, "b": user_b_id},
    )
    await owner_session.execute(
        text("DELETE FROM tenants WHERE id IN (:a, :b)"),
        {"a": tenant_a_id, "b": tenant_b_id},
    )
    await owner_session.commit()


async def test_rls_tenant_a_sees_only_own_users(runtime_session, two_tenants):
    """Tenant A context should only see Tenant A's users."""
    tid = str(two_tenants["tenant_a"])
    await runtime_session.execute(
        text("SELECT set_config('app.current_tenant_id', :tid, true)"),
        {"tid": tid},
    )
    result = await runtime_session.execute(text("SELECT id FROM users"))
    rows = result.fetchall()
    user_ids = {row[0] for row in rows}
    assert two_tenants["user_a"] in user_ids
    assert two_tenants["user_b"] not in user_ids


async def test_rls_tenant_b_sees_only_own_users(runtime_session, two_tenants):
    """Tenant B context should only see Tenant B's users."""
    tid = str(two_tenants["tenant_b"])
    await runtime_session.execute(
        text("SELECT set_config('app.current_tenant_id', :tid, true)"),
        {"tid": tid},
    )
    result = await runtime_session.execute(text("SELECT id FROM users"))
    rows = result.fetchall()
    user_ids = {row[0] for row in rows}
    assert two_tenants["user_b"] in user_ids
    assert two_tenants["user_a"] not in user_ids


async def test_rls_no_context_sees_nothing(runtime_session, two_tenants):
    """Without tenant context set, runtime role should see no rows (UUID cast error)."""
    import sqlalchemy.exc

    # An empty tenant_id causes a UUID cast error — preventing any data leak
    await runtime_session.execute(
        text("SELECT set_config('app.current_tenant_id', '', true)")
    )
    with pytest.raises(sqlalchemy.exc.DataError):
        await runtime_session.execute(text("SELECT id FROM users"))
    await runtime_session.rollback()


async def test_rls_tenant_sees_only_own_tenant_row(runtime_session, two_tenants):
    """Tenant context on tenants table: only own tenant visible."""
    tid = str(two_tenants["tenant_a"])
    await runtime_session.execute(
        text("SELECT set_config('app.current_tenant_id', :tid, true)"),
        {"tid": tid},
    )
    result = await runtime_session.execute(text("SELECT id FROM tenants"))
    rows = result.fetchall()
    tenant_ids = {row[0] for row in rows}
    assert two_tenants["tenant_a"] in tenant_ids
    assert two_tenants["tenant_b"] not in tenant_ids
