"""seed_default_tenant_and_owner

Revision ID: ef7f95410110
Revises: f7e098064859
Create Date: 2026-04-07 16:41:07.613835

"""
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pwdlib import PasswordHash


# revision identifiers, used by Alembic.
revision: str = 'ef7f95410110'
down_revision: Union[str, Sequence[str], None] = 'f7e098064859'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Well-known UUIDs for the default tenant/owner — makes idempotent & referenceable
DEFAULT_TENANT_ID = "00000000-0000-4000-a000-000000000001"
DEFAULT_OWNER_ID = "00000000-0000-4000-a000-000000000002"


def upgrade() -> None:
    """Seed the default tenant and owner user (admin bootstrap)."""
    owner_email = os.environ.get("SEED_OWNER_EMAIL")
    owner_password = os.environ.get("SEED_OWNER_PASSWORD")

    if not owner_email or not owner_password:
        raise RuntimeError(
            "SEED_OWNER_EMAIL and SEED_OWNER_PASSWORD must be set "
            "when running the bootstrap seed migration."
        )

    password_hash = PasswordHash.recommended()
    hashed = password_hash.hash(owner_password)

    op.execute(
        sa.text(
            """
            INSERT INTO tenants (id, name, subscription_plan, subscription_status, is_active)
            VALUES (CAST(:id AS uuid), :name, :plan, :status, true)
            ON CONFLICT (id) DO NOTHING
            """
        ).bindparams(
            id=DEFAULT_TENANT_ID,
            name="Default",
            plan="enterprise",
            status="active",
        )
    )

    op.execute(
        sa.text(
            """
            INSERT INTO users (id, tenant_id, email, role, hashed_password, is_active)
            VALUES (CAST(:id AS uuid), CAST(:tenant_id AS uuid), :email, :role, :hashed_password, true)
            ON CONFLICT (id) DO NOTHING
            """
        ).bindparams(
            id=DEFAULT_OWNER_ID,
            tenant_id=DEFAULT_TENANT_ID,
            email=owner_email,
            role="owner",
            hashed_password=hashed,
        )
    )


def downgrade() -> None:
    """Remove seed data."""
    op.execute(
        sa.text("DELETE FROM users WHERE id = CAST(:id AS uuid)").bindparams(
            id=DEFAULT_OWNER_ID
        )
    )
    op.execute(
        sa.text("DELETE FROM tenants WHERE id = CAST(:id AS uuid)").bindparams(
            id=DEFAULT_TENANT_ID
        )
    )
