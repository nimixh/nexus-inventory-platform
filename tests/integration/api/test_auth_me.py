from httpx import AsyncClient


async def test_me_with_valid_token(
    client: AsyncClient, registered_user: dict, auth_headers: dict
):
    resp = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == registered_user["email"]
    assert data["is_active"] is True
    assert "id" in data
    assert "created_at" in data
    # Must NOT contain sensitive fields
    assert "hashed_password" not in data


async def test_me_without_token(client: AsyncClient):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_me_with_invalid_token(client: AsyncClient):
    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid.jwt.token"},
    )
    assert resp.status_code == 401
