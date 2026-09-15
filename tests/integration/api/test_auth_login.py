from httpx import AsyncClient


async def test_login_success(client: AsyncClient, registered_user: dict):
    resp = await client.post(
        "/api/v1/auth/login",
        data={
            "username": registered_user["email"],
            "password": registered_user["password"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" not in data
    assert data["token_type"] == "bearer"
    assert resp.cookies.get("refresh_token")
    set_cookie = resp.headers.get("set-cookie", "").lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/api/v1/auth" in set_cookie


async def test_login_wrong_password(client: AsyncClient, registered_user: dict):
    resp = await client.post(
        "/api/v1/auth/login",
        data={
            "username": registered_user["email"],
            "password": "WrongPassword123!",
        },
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Incorrect username or password"


async def test_login_nonexistent_user(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "nobody@example.com", "password": "Whatever123!"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Incorrect username or password"


async def test_login_inactive_user(client: AsyncClient, inactive_user: dict):
    resp = await client.post(
        "/api/v1/auth/login",
        data={
            "username": inactive_user["email"],
            "password": inactive_user["password"],
        },
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Incorrect username or password"
