"""Tests for TenantMixin — verifies the metadata contract for RLS detection."""

from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin


class _TestModel(TenantMixin, Base):
    """Throwaway model used only in this test module."""

    __tablename__ = "_test_tenant_mixin"

    id: Mapped[int] = mapped_column(primary_key=True)


def test_rls_marker_on_tenant_column():
    """TenantMixin columns carry info.rls so Alembic can detect them."""
    table = Base.metadata.tables["_test_tenant_mixin"]
    assert table.c.tenant_id.info.get("rls") is True


def test_rls_marker_absent_on_non_tenant_table():
    """Tables without TenantMixin do not have the RLS marker."""
    table = Base.metadata.tables["tenants"]
    assert not any(col.info.get("rls", False) for col in table.columns)
