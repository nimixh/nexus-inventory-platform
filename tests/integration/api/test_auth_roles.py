"""Tests for role-based authorization and tenant-aware features."""

from httpx import AsyncClient

from app.dependencies.auth import RequireRole
from app.models.enums import UserRole
from app.models.user import User


async def test_me_returns_tenant_and_role(
    client: AsyncClient, auth_headers: dict, tenant
):
    """GET /me should return tenant_id and role."""
    resp = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["tenant_id"] == str(tenant.id)
    assert data["role"] == "viewer"
    assert "last_login" in data


class TestRequireRole:
    def test_allowed_role_passes(self):
        checker = RequireRole(UserRole.OWNER, UserRole.ADMIN)
        user = User(
            email="t@t.com",
            hashed_password="x",
            tenant_id="00000000-0000-4000-a000-000000000001",
            role=UserRole.OWNER,
        )
        result = checker(user)
        assert result is user

    def test_disallowed_role_raises_403(self):
        import pytest
        from fastapi import HTTPException

        checker = RequireRole(UserRole.OWNER, UserRole.ADMIN)
        user = User(
            email="t@t.com",
            hashed_password="x",
            tenant_id="00000000-0000-4000-a000-000000000001",
            role=UserRole.VIEWER,
        )
        with pytest.raises(HTTPException) as exc_info:
            checker(user)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Insufficient permissions"
