"""enable_rls_on_users

Revision ID: f7e098064859
Revises: 444a0c65e4f0
Create Date: 2026-04-07 16:35:05.602784

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7e098064859'
down_revision: Union[str, Sequence[str], None] = '444a0c65e4f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Create 'app' schema for helper functions
    op.execute("CREATE SCHEMA IF NOT EXISTS app")

    # 2. Helper function: returns the current tenant_id from session config
    op.execute("""
        CREATE OR REPLACE FUNCTION app.current_tenant_id()
        RETURNS uuid
        LANGUAGE sql STABLE
        AS $$
            SELECT current_setting('app.current_tenant_id', true)::uuid
        $$
    """)

    # 3. Enable RLS on users table
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    # Owner (nexus) bypasses RLS; force it for all other roles
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")

    # 4. Policies for nexus_runtime role
    op.execute("""
        CREATE POLICY tenant_isolation_select ON users
            FOR SELECT
            TO nexus_runtime
            USING (tenant_id = app.current_tenant_id())
    """)
    op.execute("""
        CREATE POLICY tenant_isolation_insert ON users
            FOR INSERT
            TO nexus_runtime
            WITH CHECK (tenant_id = app.current_tenant_id())
    """)
    op.execute("""
        CREATE POLICY tenant_isolation_update ON users
            FOR UPDATE
            TO nexus_runtime
            USING (tenant_id = app.current_tenant_id())
            WITH CHECK (tenant_id = app.current_tenant_id())
    """)
    op.execute("""
        CREATE POLICY tenant_isolation_delete ON users
            FOR DELETE
            TO nexus_runtime
            USING (tenant_id = app.current_tenant_id())
    """)

    # 5. Enable RLS on tenants table (tenant can only see own row)
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_self_select ON tenants
            FOR SELECT
            TO nexus_runtime
            USING (id = app.current_tenant_id())
    """)

    # Grant EXECUTE on function to nexus_runtime
    op.execute("GRANT USAGE ON SCHEMA app TO nexus_runtime")
    op.execute("GRANT EXECUTE ON FUNCTION app.current_tenant_id() TO nexus_runtime")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS tenant_self_select ON tenants")
    op.execute("ALTER TABLE tenants DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants NO FORCE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS tenant_isolation_delete ON users")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_update ON users")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_insert ON users")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_select ON users")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users NO FORCE ROW LEVEL SECURITY")

    op.execute("DROP FUNCTION IF EXISTS app.current_tenant_id()")
    op.execute("DROP SCHEMA IF EXISTS app")
