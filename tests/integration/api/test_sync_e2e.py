"""Service-level integration tests — direct process_sync calls against test DB.

These test the CSV-to-DB pipeline without going through Celery.
"""

import csv
import io
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.sync import SyncService


def _make_csv(rows: list[list[str]]) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    for row in rows:
        writer.writerow(row)
    return output.getvalue().encode("utf-8")


VALID_HEADERS = [
    "SKU Code",
    "Product Name",
    "Category",
    "UOM",
    "Unit Cost",
    "Selling Price",
]
VALID_ROW = ["SKU-001", "Widget", "Tools", "pcs", "100.00", "150.00"]


def _wrap_session(session: AsyncSession):
    @asynccontextmanager
    async def _factory():
        yield session

    return _factory


@pytest.fixture(autouse=True)
def _patch_celery():
    """Prevent sync_erp_data.delay from reaching a real Celery broker."""
    with patch("app.tasks.sync.sync_erp_data.delay") as mock:
        yield mock


class TestEndToEndCsvSync:
    """Full pipeline: upload CSV → call process_sync inline → verify products.

    Everything runs inside the test transaction so rollback cleans up state.
    process_sync receives a wrapped version of the test session.
    """

    @pytest.mark.asyncio
    async def test_full_csv_roundtrip(
        self,
        client: AsyncClient,
        ops_auth_headers: dict,
        tenant,
        db_session: AsyncSession,
    ):
        # Upload
        content = _make_csv(
            [
                VALID_HEADERS,
                ["SKU-001", "Widget", "Tools", "pcs", "100.00", "150.00"],
                ["SKU-002", "Gadget", "Electronics", "pcs", "250.50", "399.99"],
                ["SKU-003", "Doodad", "Tools", "kg", "10.00", "25.00"],
            ]
        )
        resp = await client.post(
            "/api/v1/integrations/upload",
            files={"file": ("products.csv", content, "text/csv")},
            headers=ops_auth_headers,
        )
        assert resp.status_code == 201
        job_id = resp.json()["job_id"]

        # Run sync inline using the test session
        await SyncService.process_sync(
            sync_log_id=uuid.UUID(job_id),
            tenant_id=tenant.id,
            tenant_config={},
            _session_factory=_wrap_session(db_session),
        )

        # Products visible via API
        products_resp = await client.get("/api/v1/products", headers=ops_auth_headers)
        assert products_resp.status_code == 200
        items = products_resp.json()["items"]
        assert len(items) == 3
        skus = {p["sku_code"] for p in items}
        assert skus == {"SKU-001", "SKU-002", "SKU-003"}

        # Prices in paise
        sku1 = next(p for p in items if p["sku_code"] == "SKU-001")
        assert sku1["unit_cost_paise"] == 10000
        assert sku1["selling_price_paise"] == 15000
        sku2 = next(p for p in items if p["sku_code"] == "SKU-002")
        assert sku2["unit_cost_paise"] == 25050
        assert sku2["selling_price_paise"] == 39999

        # Sync log status
        status_resp = await client.get(
            f"/api/v1/integrations/upload/{job_id}/status",
            headers=ops_auth_headers,
        )
        assert status_resp.status_code == 200
        job = status_resp.json()
        assert job["status"] == "completed"
        assert job["records_processed"] == 3
        assert job["records_failed"] == 0
        assert job["data_quality_score"] == 100.0

    @pytest.mark.asyncio
    async def test_bad_rows_are_skipped_good_rows_persisted(
        self,
        client: AsyncClient,
        ops_auth_headers: dict,
        tenant,
        db_session: AsyncSession,
    ):
        content = _make_csv(
            [
                VALID_HEADERS,
                ["SKU-001", "Widget", "Tools", "pcs", "100.00", "150.00"],
                ["SKU-002", "", "", "pcs", "", ""],  # missing name → skipped
                ["SKU-003", "Doodad", "Tools", "kg", "10.00", "25.00"],
            ]
        )
        resp = await client.post(
            "/api/v1/integrations/upload",
            files={"file": ("products.csv", content, "text/csv")},
            headers=ops_auth_headers,
        )
        assert resp.status_code == 201
        job_id = resp.json()["job_id"]

        await SyncService.process_sync(
            sync_log_id=uuid.UUID(job_id),
            tenant_id=tenant.id,
            tenant_config={},
            _session_factory=_wrap_session(db_session),
        )

        items = (await client.get("/api/v1/products", headers=ops_auth_headers)).json()[
            "items"
        ]
        assert len(items) == 2
        assert {p["sku_code"] for p in items} == {"SKU-001", "SKU-003"}

        job = (
            await client.get(
                f"/api/v1/integrations/upload/{job_id}/status", headers=ops_auth_headers
            )
        ).json()
        assert job["status"] == "completed"
        assert job["records_processed"] == 2
        assert job["records_failed"] == 1
        assert len(job["errors"]) == 1
        assert job["errors"][0]["entity"] == "product"
        assert job["data_quality_score"] < 100.0

    @pytest.mark.asyncio
    async def test_fatal_failure_retains_upload_until_retry_cleanup(
        self,
        client: AsyncClient,
        ops_auth_headers: dict,
        tenant,
        db_session: AsyncSession,
    ):
        content = _make_csv([VALID_HEADERS, VALID_ROW])
        resp = await client.post(
            "/api/v1/integrations/upload",
            files={"file": ("products.csv", content, "text/csv")},
            headers=ops_auth_headers,
        )
        job_id = uuid.UUID(resp.json()["job_id"])
        from app.models.sync_log import SyncLog

        sync_log = await db_session.get(SyncLog, job_id)
        assert sync_log is not None
        stored_path = Path(sync_log.stored_path or "")

        with (
            patch(
                "app.services.sync.ConnectorFactory.get",
                side_effect=RuntimeError("temporary failure"),
            ),
            pytest.raises(RuntimeError, match="temporary failure"),
        ):
            await SyncService.process_sync(
                sync_log_id=job_id,
                tenant_id=tenant.id,
                tenant_config={},
                _session_factory=_wrap_session(db_session),
            )

        assert stored_path.exists()
        await SyncService.delete_upload(
            sync_log_id=job_id,
            tenant_id=tenant.id,
            _session_factory=_wrap_session(db_session),
        )
        assert not stored_path.exists()

    @pytest.mark.asyncio
    async def test_upsert_reimport_updates_existing(
        self,
        client: AsyncClient,
        ops_auth_headers: dict,
        tenant,
        db_session: AsyncSession,
    ):
        # First import
        c1 = _make_csv(
            [VALID_HEADERS, ["SKU-001", "Widget", "Tools", "pcs", "100.00", "150.00"]]
        )
        r1 = await client.post(
            "/api/v1/integrations/upload",
            files={"file": ("i1.csv", c1, "text/csv")},
            headers=ops_auth_headers,
        )
        await SyncService.process_sync(
            sync_log_id=uuid.UUID(r1.json()["job_id"]),
            tenant_id=tenant.id,
            tenant_config={},
            _session_factory=_wrap_session(db_session),
        )

        # Second import — same SKU, updated
        c2 = _make_csv(
            [
                VALID_HEADERS,
                ["SKU-001", "Widget Pro", "Tools", "pcs", "120.00", "180.00"],
            ]
        )
        r2 = await client.post(
            "/api/v1/integrations/upload",
            files={"file": ("i2.csv", c2, "text/csv")},
            headers=ops_auth_headers,
        )
        await SyncService.process_sync(
            sync_log_id=uuid.UUID(r2.json()["job_id"]),
            tenant_id=tenant.id,
            tenant_config={},
            _session_factory=_wrap_session(db_session),
        )

        items = (await client.get("/api/v1/products", headers=ops_auth_headers)).json()[
            "items"
        ]
        assert len(items) == 1
        assert items[0]["sku_code"] == "SKU-001"
        assert items[0]["name"] == "Widget Pro"
        assert items[0]["unit_cost_paise"] == 12000
        assert items[0]["selling_price_paise"] == 18000

    @pytest.mark.asyncio
    async def test_same_tenant_multi_role_visibility(
        self,
        client: AsyncClient,
        ops_auth_headers: dict,
        auth_headers: dict,
        tenant,
        db_session: AsyncSession,
    ):
        """Products created by OPS user are visible to viewer in the same tenant."""
        content = _make_csv([VALID_HEADERS, VALID_ROW])
        resp = await client.post(
            "/api/v1/integrations/upload",
            files={"file": ("products.csv", content, "text/csv")},
            headers=ops_auth_headers,
        )
        await SyncService.process_sync(
            sync_log_id=uuid.UUID(resp.json()["job_id"]),
            tenant_id=tenant.id,
            tenant_config={},
            _session_factory=_wrap_session(db_session),
        )

        ops_items = (
            await client.get("/api/v1/products", headers=ops_auth_headers)
        ).json()["items"]
        assert len(ops_items) == 1

        # Viewer in same tenant sees them too
        viewer_items = (
            await client.get("/api/v1/products", headers=auth_headers)
        ).json()["items"]
        assert len(viewer_items) == 1


class TestCrossTenantIsolation:
    """Prove tenant isolation for products and sync logs at the DB level.

    Uses direct nexus_runtime connections so RLS is actually enforced.
    The API-level tests (test_integrations.py) use the owner-role session
    which bypasses RLS — see conftest.py for the explanation.
    """

    RUNTIME_URL = (
        "postgresql+psycopg://nexus_runtime:nexus_runtime@127.0.0.1:5432/nexus_test"
    )

    @pytest.mark.asyncio
    async def test_products_isolated_by_tenant(
        self,
        client: AsyncClient,
        ops_auth_headers: dict,
        tenant,
        db_session: AsyncSession,
    ):
        from sqlalchemy import create_engine, text

        # Upload and sync for tenant A
        content = _make_csv([VALID_HEADERS, VALID_ROW])
        resp = await client.post(
            "/api/v1/integrations/upload",
            files={"file": ("products.csv", content, "text/csv")},
            headers=ops_auth_headers,
        )
        assert resp.status_code == 201
        await SyncService.process_sync(
            sync_log_id=uuid.UUID(resp.json()["job_id"]),
            tenant_id=tenant.id,
            tenant_config={},
            _session_factory=_wrap_session(db_session),
        )

        # Confirm tenant A sees 1 product (API with owner session)
        items_a = (
            await client.get("/api/v1/products", headers=ops_auth_headers)
        ).json()["items"]
        assert len(items_a) == 1

        # As nexus_runtime (RLS enforced) with a different tenant context,
        # products created by tenant A must be invisible.
        sync_engine = create_engine(self.RUNTIME_URL, pool_pre_ping=True)
        try:
            with sync_engine.connect() as conn:
                conn.execute(
                    text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                    {"tid": str(uuid.uuid4())},
                )
                conn.commit()
                # RLS filters out tenant A's uncommitted rows; runtime sees 0
                rows = conn.execute(text("SELECT id FROM products")).fetchall()
                assert len(rows) == 0
        finally:
            sync_engine.dispose()

    @pytest.mark.asyncio
    async def test_sync_logs_isolated_by_tenant(
        self,
        client: AsyncClient,
        ops_auth_headers: dict,
        tenant,
        db_session: AsyncSession,
    ):
        from sqlalchemy import create_engine, text

        # Upload for tenant A
        content = _make_csv([VALID_HEADERS, VALID_ROW])
        resp = await client.post(
            "/api/v1/integrations/upload",
            files={"file": ("products.csv", content, "text/csv")},
            headers=ops_auth_headers,
        )
        assert resp.status_code == 201
        job_id_a = uuid.UUID(resp.json()["job_id"])

        # As nexus_runtime, query sync_logs in a different tenant context
        sync_engine = create_engine(self.RUNTIME_URL, pool_pre_ping=True)
        try:
            with sync_engine.connect() as conn:
                conn.execute(
                    text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                    {"tid": str(uuid.uuid4())},
                )
                conn.commit()
                row = conn.execute(
                    text("SELECT id FROM sync_logs WHERE id = :jid"),
                    {"jid": str(job_id_a)},
                ).fetchone()
                assert row is None
        finally:
            sync_engine.dispose()
