import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserRole
from app.repositories.user import create_user
from app.security import create_access_token, hash_password


async def _headers_for_role(
    db: AsyncSession, tenant_id: uuid.UUID, role: UserRole
) -> dict[str, str]:
    user = await create_user(
        db,
        email=f"{role.value}-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("StrongPass123!"),
        tenant_id=tenant_id,
        role=role,
    )
    await db.flush()
    token = create_access_token(str(user.id), str(user.tenant_id), user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def test_public_registration_endpoint_does_not_exist(client: AsyncClient, tenant):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "public@example.com",
            "password": "StrongPass1!",
            "tenant_id": str(tenant.id),
        },
    )
    assert response.status_code == 404


async def test_user_provisioning_requires_authentication(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/users",
        json={"email": "new@example.com", "password": "StrongPass1!"},
    )
    assert response.status_code == 401


async def test_viewer_cannot_provision_users(client: AsyncClient, auth_headers: dict):
    response = await client.post(
        "/api/v1/auth/users",
        json={"email": "new@example.com", "password": "StrongPass1!"},
        headers=auth_headers,
    )
    assert response.status_code == 403


async def test_ops_cannot_provision_users(client: AsyncClient, ops_auth_headers: dict):
    response = await client.post(
        "/api/v1/auth/users",
        json={"email": "new@example.com", "password": "StrongPass1!"},
        headers=ops_auth_headers,
    )
    assert response.status_code == 403


async def test_owner_provisions_viewer_in_own_tenant(
    client: AsyncClient, db_session: AsyncSession, tenant
):
    headers = await _headers_for_role(db_session, tenant.id, UserRole.OWNER)
    response = await client.post(
        "/api/v1/auth/users",
        json={"email": "new@example.com", "password": "StrongPass1!"},
        headers=headers,
    )
    assert response.status_code == 201
    assert response.json()["email"] == "new@example.com"
    assert response.json()["tenant_id"] == str(tenant.id)
    assert response.json()["role"] == "viewer"


async def test_admin_provisions_viewer_in_own_tenant(
    client: AsyncClient, db_session: AsyncSession, tenant
):
    headers = await _headers_for_role(db_session, tenant.id, UserRole.ADMIN)
    response = await client.post(
        "/api/v1/auth/users",
        json={"email": "admin-created@example.com", "password": "StrongPass1!"},
        headers=headers,
    )
    assert response.status_code == 201
    assert response.json()["tenant_id"] == str(tenant.id)


async def test_provisioning_rejects_caller_selected_tenant(
    client: AsyncClient, db_session: AsyncSession, tenant
):
    headers = await _headers_for_role(db_session, tenant.id, UserRole.OWNER)
    response = await client.post(
        "/api/v1/auth/users",
        json={
            "email": "cross-tenant@example.com",
            "password": "StrongPass1!",
            "tenant_id": str(uuid.uuid4()),
        },
        headers=headers,
    )
    assert response.status_code == 422


async def test_provisioning_rejects_caller_selected_role(
    client: AsyncClient, db_session: AsyncSession, tenant
):
    headers = await _headers_for_role(db_session, tenant.id, UserRole.OWNER)
    response = await client.post(
        "/api/v1/auth/users",
        json={
            "email": "escalation@example.com",
            "password": "StrongPass1!",
            "role": "owner",
        },
        headers=headers,
    )
    assert response.status_code == 422


async def test_provisioning_enforces_password_policy(
    client: AsyncClient, db_session: AsyncSession, tenant
):
    headers = await _headers_for_role(db_session, tenant.id, UserRole.OWNER)
    response = await client.post(
        "/api/v1/auth/users",
        json={"email": "weak@example.com", "password": "password"},
        headers=headers,
    )
    assert response.status_code == 422


async def test_provisioning_rejects_duplicate_email(
    client: AsyncClient, db_session: AsyncSession, tenant
):
    headers = await _headers_for_role(db_session, tenant.id, UserRole.OWNER)
    payload = {"email": "duplicate@example.com", "password": "StrongPass1!"}
    first = await client.post("/api/v1/auth/users", json=payload, headers=headers)
    second = await client.post("/api/v1/auth/users", json=payload, headers=headers)
    assert first.status_code == 201
    assert second.status_code == 409
