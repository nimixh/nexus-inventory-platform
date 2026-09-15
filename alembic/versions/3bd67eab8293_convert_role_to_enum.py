"""convert_role_to_enum

Revision ID: 3bd67eab8293
Revises: ef7f95410110
Create Date: 2026-04-08 02:01:24.978341

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3bd67eab8293'
down_revision: Union[str, Sequence[str], None] = 'ef7f95410110'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Normalise any non-conforming role values before the cast
    op.execute(
        sa.text(
            "UPDATE users SET role = 'viewer' "
            "WHERE role NOT IN ('owner', 'admin', 'ops', 'viewer')"
        )
    )

    # Create the enum type first
    user_role_enum = sa.Enum('owner', 'admin', 'ops', 'viewer', name='user_role_enum')
    user_role_enum.create(op.get_bind(), checkfirst=True)

    # Convert the column from VARCHAR to the enum type
    op.alter_column(
        'users',
        'role',
        existing_type=sa.VARCHAR(length=20),
        type_=user_role_enum,
        existing_nullable=False,
        postgresql_using='role::user_role_enum',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        'users',
        'role',
        existing_type=sa.Enum('owner', 'admin', 'ops', 'viewer', name='user_role_enum'),
        type_=sa.VARCHAR(length=20),
        existing_nullable=False,
        postgresql_using='role::text',
    )
    # Drop the enum type
    sa.Enum(name='user_role_enum').drop(op.get_bind(), checkfirst=True)
