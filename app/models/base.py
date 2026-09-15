import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(AsyncAttrs, DeclarativeBase):
    pass


class TenantMixin:
    """Mixin for models that need tenant scoping + auto-RLS.

    Adds a ``tenant_id`` FK and marks the column via ``info={"rls": True}``
    so the Alembic auto-RLS hook can detect tenant-scoped tables during
    ``--autogenerate``.
    """

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        index=True,
        info={"rls": True},
    )
