"""Auto-RLS hook for Alembic autogenerate.

Detects tenant-scoped tables (those with a column carrying ``info={"rls": True}``)
during ``alembic revision --autogenerate`` and appends the DDL to enable
row-level security, force it, and create the tenant isolation policy.

Extracted from ``alembic/env.py`` so it can be imported and unit-tested
without Alembic's runtime bootstrap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alembic.operations import ops

if TYPE_CHECKING:
    from sqlalchemy import MetaData

RUNTIME_ROLE = "nexus_runtime"
TENANT_SETTING = "app.current_tenant_id"


def rls_upgrade_sql(table_name: str, tenant_col: str = "tenant_id") -> list[str]:
    """Return the SQL statements to enable RLS on a table."""
    policy = f"tenant_isolation_{table_name}"
    return [
        f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY",
        (
            f"CREATE POLICY {policy} ON {table_name} "
            f"FOR ALL TO {RUNTIME_ROLE} "
            f"USING ({tenant_col} = {TENANT_SETTING}()) "
            f"WITH CHECK ({tenant_col} = {TENANT_SETTING}())"
        ),
    ]


def rls_downgrade_sql(table_name: str) -> list[str]:
    """Return the SQL statements to remove RLS from a table."""
    policy = f"tenant_isolation_{table_name}"
    return [
        f"DROP POLICY IF EXISTS {policy} ON {table_name}",
        f"ALTER TABLE {table_name} NO FORCE ROW LEVEL SECURITY",
        f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY",
    ]


def is_rls_table(metadata: MetaData, table_name: str) -> bool:
    """Check if a table has a column with the RLS flag set via Column.info."""
    table = metadata.tables.get(table_name)
    if table is not None:
        return any(col.info.get("rls", False) for col in table.columns)
    return False


def make_process_revision_directives(
    metadata: MetaData,
) -> Any:
    """Return the ``process_revision_directives`` callback bound to *metadata*."""

    def process_revision_directives(
        context: Any,  # noqa: ARG001
        revision: Any,  # noqa: ARG001
        directives: list[Any],
    ) -> None:
        """Append RLS operations for any new tenant-scoped table."""
        script = directives[0]
        upgrade_ops = script.upgrade_ops
        downgrade_ops = script.downgrade_ops

        rls_tables: list[str] = []
        for op in list(upgrade_ops.ops):
            if isinstance(op, ops.CreateTableOp) and is_rls_table(
                metadata, op.table_name
            ):
                rls_tables.append(op.table_name)

        for table_name in rls_tables:
            for sql in rls_upgrade_sql(table_name):
                upgrade_ops.ops.append(ops.ExecuteSQLOp(sql))
            for sql in reversed(rls_downgrade_sql(table_name)):
                downgrade_ops.ops.insert(0, ops.ExecuteSQLOp(sql))

    return process_revision_directives
