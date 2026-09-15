"""Tests that the auto-RLS hook generates correct RLS operations.

Imports the real hook from app.rls and exercises it with real Alembic
directive objects — no duplicated production logic.
"""

from alembic.operations import ops

import app.models  # noqa: F401 — populate metadata
from app.models.base import Base
from app.rls import (
    is_rls_table,
    make_process_revision_directives,
    rls_downgrade_sql,
    rls_upgrade_sql,
)

metadata = Base.metadata


def _build_directives(table_name: str) -> list[ops.MigrationScript]:
    """Build a minimal MigrationScript with a CreateTableOp."""
    create_op = ops.CreateTableOp(table_name, [])
    upgrade = ops.UpgradeOps(ops=[create_op])
    downgrade = ops.DowngradeOps(ops=[])
    script = ops.MigrationScript(
        rev_id="test",
        upgrade_ops=upgrade,
        downgrade_ops=downgrade,
    )
    return [script]


def test_hook_appends_rls_for_tenant_table():
    """Hook adds ENABLE/FORCE RLS + CREATE POLICY for a TenantMixin table."""
    hook = make_process_revision_directives(metadata)
    directives = _build_directives("users")

    hook(None, None, directives)

    upgrade = directives[0].upgrade_ops.ops
    assert len(upgrade) == 4  # CreateTable + 3 RLS statements

    rls_sqls = [op.sqltext for op in upgrade[1:]]
    assert "ALTER TABLE users ENABLE ROW LEVEL SECURITY" in rls_sqls
    assert "ALTER TABLE users FORCE ROW LEVEL SECURITY" in rls_sqls
    assert any("CREATE POLICY" in s and "nexus_runtime" in s for s in rls_sqls)


def test_hook_generates_downgrade_ops():
    """Hook generates DROP POLICY + NO FORCE + DISABLE RLS for downgrade."""
    hook = make_process_revision_directives(metadata)
    directives = _build_directives("users")

    hook(None, None, directives)

    downgrade = directives[0].downgrade_ops.ops
    assert len(downgrade) == 3

    down_sqls = [op.sqltext for op in downgrade]
    assert any("DROP POLICY" in s for s in down_sqls)
    assert any("NO FORCE" in s for s in down_sqls)
    assert any("DISABLE ROW LEVEL SECURITY" in s for s in down_sqls)


def test_hook_skips_non_tenant_table():
    """Hook does NOT generate RLS for tables without TenantMixin."""
    hook = make_process_revision_directives(metadata)
    directives = _build_directives("tenants")

    hook(None, None, directives)

    upgrade = directives[0].upgrade_ops.ops
    assert len(upgrade) == 1  # Only the original CreateTableOp
    assert isinstance(upgrade[0], ops.CreateTableOp)

    downgrade = directives[0].downgrade_ops.ops
    assert len(downgrade) == 0


def test_is_rls_table_detection():
    """is_rls_table correctly identifies tenant vs shared tables."""
    assert is_rls_table(metadata, "users") is True
    assert is_rls_table(metadata, "tenants") is False
    assert is_rls_table(metadata, "nonexistent") is False


def test_rls_sql_content():
    """Generated SQL contains the expected policy name and clauses."""
    upgrade_stmts = rls_upgrade_sql("orders")
    assert len(upgrade_stmts) == 3
    assert "tenant_isolation_orders" in upgrade_stmts[2]
    assert "WITH CHECK" in upgrade_stmts[2]

    downgrade_stmts = rls_downgrade_sql("orders")
    assert len(downgrade_stmts) == 3
    assert "tenant_isolation_orders" in downgrade_stmts[0]
