from httpx import AsyncClient


async def test_logout_revokes_refresh_token(client: AsyncClient, registered_user: dict):
    client.cookies.set("refresh_token", registered_user["refresh_token"])
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 204
    set_cookie = resp.headers.get("set-cookie", "").lower()
    assert "refresh_token=" in set_cookie
    assert "max-age=0" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/api/v1/auth" in set_cookie

    # Refresh with revoked token should fail
    client.cookies.set("refresh_token", registered_user["refresh_token"])
    resp2 = await client.post("/api/v1/auth/refresh")
    assert resp2.status_code == 401
    assert resp2.json()["detail"] == "Refresh token revoked or expired"


async def test_logout_missing_cookie(client: AsyncClient):
    """No cookie should return 401."""
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Refresh token missing"
