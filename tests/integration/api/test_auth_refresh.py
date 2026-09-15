from httpx import AsyncClient


async def test_refresh_success(client: AsyncClient, registered_user: dict):
    client.cookies.set("refresh_token", registered_user["refresh_token"])
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" not in data  # must not leak in body
    # New refresh token should be in cookie, not body
    new_refresh = resp.cookies.get("refresh_token", "")
    assert new_refresh
    assert new_refresh != registered_user["refresh_token"]
    set_cookie = resp.headers.get("set-cookie", "").lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/api/v1/auth" in set_cookie


async def test_refresh_reuse_after_rotation(client: AsyncClient, registered_user: dict):
    """Old refresh token should fail after it's been used (rotation)."""
    old_refresh = registered_user["refresh_token"]

    # First refresh — should succeed
    client.cookies.set("refresh_token", old_refresh)
    resp1 = await client.post("/api/v1/auth/refresh")
    assert resp1.status_code == 200

    # Same token again — should fail (already revoked via getdel)
    client.cookies.set("refresh_token", old_refresh)
    resp2 = await client.post("/api/v1/auth/refresh")
    assert resp2.status_code == 401
    assert resp2.json()["detail"] == "Refresh token revoked or expired"


async def test_refresh_invalid_token(client: AsyncClient):
    client.cookies.set("refresh_token", "not.a.valid.jwt")
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid refresh token"


async def test_refresh_with_access_token_rejected(
    client: AsyncClient, registered_user: dict
):
    """Access token must not be accepted as a refresh token (type confusion)."""
    client.cookies.set("refresh_token", registered_user["access_token"])
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid refresh token"


async def test_refresh_missing_cookie(client: AsyncClient):
    """No cookie should return 401."""
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Refresh token missing"


async def test_refresh_empty_cookie(client: AsyncClient):
    """Empty-string cookie should return 401."""
    client.cookies.set("refresh_token", "")
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Refresh token missing"


async def test_refresh_inactive_user(client: AsyncClient, inactive_user: dict):
    """Refresh for a deactivated user should fail."""
    client.cookies.set("refresh_token", inactive_user["refresh_token"])
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "User not found or inactive"
