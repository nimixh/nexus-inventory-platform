import os
import uuid
from pathlib import Path

# Set test env vars BEFORE importing the app (module-level engine/redis use these)
os.environ["DATABASE_URL"] = (
    "postgresql+psycopg://nexus:nexus@127.0.0.1:5432/nexus_test"
)
os.environ["RUNTIME_DATABASE_URL"] = (
    "postgresql+psycopg://nexus:nexus@127.0.0.1:5432/nexus_test"
)
# NOTE: Both DATABASE_URL and RUNTIME_DATABASE_URL use the same owner-level
# credentials (nexus:nexus) in this test configuration. This means RLS
# enforcement is NOT tested at the API level — the test DB session connects
# as the owner role and bypasses RLS. The RLS tests in tests/integration/
# test_rls.py use a separate nexus_runtime connection to verify that RLS
# policies are active. To catch regressions where API routes accidentally
# use the admin session instead of the tenant-scoped session, add a
# runtime-role integration test that connects as nexus_runtime and asserts
# the API behaves correctly without direct owner DB access.
os.environ["REDIS_URL"] = "redis://127.0.0.1:6379/15"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-must-be-at-least-32-chars-long"
os.environ["COOKIE_SECURE"] = "false"
os.environ.setdefault("SEED_OWNER_EMAIL", "owner@example.com")
os.environ.setdefault("SEED_OWNER_PASSWORD", "StrongPass123!")

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from app.config import get_settings
from app.database import get_admin_db, get_db, reset_tenant_context, set_tenant_context
from app.dependencies.auth import CurrentUser, get_tenant_db
from app.main import app
from app.models.enums import UserRole
from app.models.tenant import Tenant
from app.redis import get_redis
from app.repositories.user import create_user
from app.security import create_access_token, hash_password
from app.services.auth import authenticate

TEST_DATABASE_URL = os.environ["DATABASE_URL"]
TEST_REDIS_URL = os.environ["REDIS_URL"]


@pytest.fixture(autouse=True)
def isolate_uploads(tmp_path: Path):
    """Keep test uploads out of the repository working tree."""
    settings = get_settings()
    previous = settings.UPLOAD_DIR
    settings.UPLOAD_DIR = str(tmp_path / "uploads")
    try:
        yield
    finally:
        settings.UPLOAD_DIR = previous


def _alembic_config() -> Config:
    project_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(project_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    return cfg


@pytest.fixture(scope="session", autouse=True)
def ensure_test_db_migrated_to_head() -> None:
    """Keep test DB schema aligned with latest migrations before tests run."""
    cfg = _alembic_config()
    script = ScriptDirectory.from_config(cfg)
    expected_heads = set(script.get_heads())
    current_heads: set[str]
    sync_engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    migration_lock_id = 917245631
    try:
        with sync_engine.connect() as conn:
            # Serialize schema upgrades when tests run concurrently (e.g. pytest-xdist).
            conn.execute(
                text("SELECT pg_advisory_lock(:lock_id)"),
                {"lock_id": migration_lock_id},
            )
            try:
                command.upgrade(cfg, "head")
            finally:
                conn.execute(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": migration_lock_id},
                )

        with sync_engine.connect() as conn:
            current_heads = set(MigrationContext.configure(conn).get_current_heads())

        # Grant nexus_runtime access to all tables (including newly migrated ones)
        # so RLS-enforced tests can connect as the runtime role.
        with sync_engine.connect() as conn:
            conn.execute(
                text("""
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON ALL TABLES IN SCHEMA public TO nexus_runtime;
                GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO nexus_runtime;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                    GRANT SELECT, INSERT, UPDATE, DELETE
                    ON TABLES TO nexus_runtime;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                    GRANT USAGE ON SEQUENCES TO nexus_runtime;
                """)
            )
            conn.commit()
    finally:
        sync_engine.dispose()

    if current_heads != expected_heads:
        current_display = ",".join(sorted(current_heads)) or "None"
        expected_display = ",".join(sorted(expected_heads)) or "None"
        raise RuntimeError(
            "Test DB is not on Alembic head "
            f"(current={current_display}, expected={expected_display})"
        )


# ── Database fixtures ──────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine():
    eng = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_connection(engine):
    connection = await engine.connect()
    transaction = await connection.begin()
    try:
        yield connection
    finally:
        await transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def db_session(db_connection):
    session_factory = async_sessionmaker(
        bind=db_connection,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    async with session_factory() as session:
        yield session


# ── Redis fixtures ─────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def redis_client():
    client = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    await client.flushdb()
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()


# ── HTTP client fixture ────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client(
    db_session: AsyncSession, redis_client: Redis
) -> AsyncGenerator[AsyncClient]:
    async def override_get_db():
        yield db_session

    async def override_get_redis():
        return redis_client

    async def override_get_tenant_db(current_user: CurrentUser):
        await set_tenant_context(db_session, str(current_user.tenant_id))
        try:
            yield db_session
        finally:
            await reset_tenant_context(db_session)

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_admin_db] = override_get_db
    app.dependency_overrides[get_redis] = override_get_redis
    app.dependency_overrides[get_tenant_db] = override_get_tenant_db

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


# ── Helpers ────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def tenant(db_session: AsyncSession) -> Tenant:
    """Create a test tenant in the current transaction."""
    t = Tenant(name="Test Corp")
    db_session.add(t)
    await db_session.flush()
    return t


@pytest_asyncio.fixture
async def registered_user(
    db_session: AsyncSession, redis_client: Redis, tenant
) -> dict:
    """Create and authenticate a viewer for auth endpoint tests."""
    email = "testuser@example.com"
    password = "StrongPass123!"
    await create_user(
        db_session,
        email=email,
        hashed_password=hash_password(password),
        tenant_id=tenant.id,
        role=UserRole.VIEWER,
    )
    await db_session.flush()
    data = await authenticate(db_session, redis_client, email, password)
    data["email"] = email
    data["password"] = password
    return data


@pytest_asyncio.fixture
async def auth_headers(registered_user: dict) -> dict:
    """Authorization header for an authenticated user (default: viewer role)."""
    return {"Authorization": f"Bearer {registered_user['access_token']}"}


@pytest_asyncio.fixture
async def ops_user(db_session: AsyncSession, redis_client: Redis, tenant) -> dict:
    """Create an OPS user directly because self-registration is viewer-only."""
    email = f"ops-{uuid.uuid4().hex[:8]}@example.com"
    password = "StrongPass123!"
    user = await create_user(
        db_session,
        email=email,
        hashed_password=hash_password(password),
        tenant_id=tenant.id,
        role=UserRole.OPS,
    )
    await db_session.flush()
    access_token = create_access_token(
        subject=str(user.id), tenant_id=str(user.tenant_id), role=user.role.value
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": 1800,
        "email": email,
        "password": password,
        "refresh_token": "",
    }


@pytest_asyncio.fixture
async def ops_auth_headers(ops_user: dict) -> dict:
    """Authorization header for an OPS-role user."""
    return {"Authorization": f"Bearer {ops_user['access_token']}"}


@pytest_asyncio.fixture
async def inactive_user(db_session: AsyncSession, redis_client: Redis, tenant) -> dict:
    """Create a user, issue tokens, then deactivate the account."""
    email = "inactive@example.com"
    password = "StrongPass123!"
    await create_user(
        db_session,
        email=email,
        hashed_password=hash_password(password),
        tenant_id=tenant.id,
        role=UserRole.VIEWER,
    )
    await db_session.flush()
    data = await authenticate(db_session, redis_client, email, password)

    # Deactivate via direct DB update within the test transaction
    from sqlalchemy import update

    from app.models.user import User

    await db_session.execute(
        update(User).where(User.email == email).values(is_active=False)
    )
    await db_session.flush()

    data["email"] = email
    data["password"] = password
    return data
