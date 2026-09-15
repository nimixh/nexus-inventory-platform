from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.redis import get_redis


async def test_health_ok(client: AsyncClient):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["db"] == "connected"
    assert data["redis"] == "connected"
    assert data["version"] == get_settings().APP_VERSION


async def test_health_degraded_db():
    """Health returns 503 when DB is unreachable."""
    broken_session = AsyncMock()
    broken_session.execute = AsyncMock(side_effect=ConnectionError("refused"))

    async def override_db():
        yield broken_session

    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/v1/health")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["db"] == "disconnected"
        assert data["redis"] == "connected"
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_health_degraded_redis():
    """Health returns 503 when Redis is unreachable."""
    broken_redis = AsyncMock()
    broken_redis.ping = AsyncMock(side_effect=ConnectionError("refused"))

    async def override_redis():
        return broken_redis

    app.dependency_overrides[get_redis] = override_redis
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/v1/health")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["db"] == "connected"
        assert data["redis"] == "disconnected"
    finally:
        app.dependency_overrides.pop(get_redis, None)
