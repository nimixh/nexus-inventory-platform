"""Integration tests for the /api/v1/integrations endpoints.

API-level tests: auth, upload, status polling, template download.
Celery dispatch is patched — see test_sync_e2e.py for pipeline tests.
"""

import csv
import io
import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.integration import JobStatusResponse
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


@pytest.fixture(autouse=True)
def _patch_celery():
    """Prevent sync_erp_data.delay from reaching a real Celery broker.

    Without this, a running Celery worker would process the sync job twice —
    once via the worker and once via any direct process_sync call in tests.
    """
    with patch("app.tasks.sync.sync_erp_data.delay") as mock:
        yield mock


class TestUploadAuth:
    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/integrations/upload",
            files={"file": ("test.csv", b"dummy", "text/csv")},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_viewer_role_returns_403(
        self, client: AsyncClient, auth_headers: dict
    ):
        content = _make_csv([VALID_HEADERS, VALID_ROW])
        response = await client.post(
            "/api/v1/integrations/upload",
            files={"file": ("products.csv", content, "text/csv")},
            headers=auth_headers,
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_rejects_invalid_file_type(
        self, client: AsyncClient, ops_auth_headers: dict
    ):
        response = await client.post(
            "/api/v1/integrations/upload",
            files={"file": ("document.txt", b"hello", "text/plain")},
            headers=ops_auth_headers,
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_rejects_legacy_xls_without_reader(
        self, client: AsyncClient, ops_auth_headers: dict
    ):
        response = await client.post(
            "/api/v1/integrations/upload",
            files={"file": ("products.xls", b"legacy", "application/vnd.ms-excel")},
            headers=ops_auth_headers,
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_uploads_csv_successfully(
        self, client: AsyncClient, ops_auth_headers: dict, _patch_celery
    ):
        content = _make_csv([VALID_HEADERS, VALID_ROW])
        response = await client.post(
            "/api/v1/integrations/upload",
            files={"file": ("products.csv", content, "text/csv")},
            headers=ops_auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "pending"

        # Verify Celery task was dispatched with correct payload
        _patch_celery.assert_called_once()
        call_kwargs = _patch_celery.call_args.kwargs
        assert "sync_log_id" in call_kwargs
        assert "tenant_id" in call_kwargs
        assert "tenant_config" in call_kwargs


class TestUploadStatus:
    @pytest.mark.asyncio
    async def test_nonexistent_job_returns_404(
        self, client: AsyncClient, auth_headers: dict
    ):
        resp = await client.get(
            f"/api/v1/integrations/upload/{uuid.uuid4()}/status",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client: AsyncClient):
        resp = await client.get(
            f"/api/v1/integrations/upload/{uuid.uuid4()}/status",
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_completed_job_returns_full_status(
        self,
        client: AsyncClient,
        ops_auth_headers: dict,
        tenant,
        db_session: AsyncSession,
    ):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _factory():
            yield db_session

        content = _make_csv([VALID_HEADERS, VALID_ROW])
        resp = await client.post(
            "/api/v1/integrations/upload",
            files={"file": ("products.csv", content, "text/csv")},
            headers=ops_auth_headers,
        )
        job_id = resp.json()["job_id"]

        await SyncService.process_sync(
            sync_log_id=uuid.UUID(job_id),
            tenant_id=tenant.id,
            tenant_config={},
            _session_factory=_factory,
        )

        status = await client.get(
            f"/api/v1/integrations/upload/{job_id}/status",
            headers=ops_auth_headers,
        )
        assert status.status_code == 200
        job = JobStatusResponse(**status.json())
        assert job.status == "completed"
        assert job.records_processed == 1
        assert job.data_quality_score == 100.0
        assert job.completed_at is not None

    @pytest.mark.asyncio
    async def test_viewer_can_poll_status(
        self,
        client: AsyncClient,
        ops_auth_headers: dict,
        auth_headers: dict,
        tenant,
        db_session: AsyncSession,
    ):
        """Viewer in same tenant can poll job status."""
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _factory():
            yield db_session

        content = _make_csv([VALID_HEADERS, VALID_ROW])
        resp = await client.post(
            "/api/v1/integrations/upload",
            files={"file": ("products.csv", content, "text/csv")},
            headers=ops_auth_headers,
        )
        job_id = resp.json()["job_id"]

        await SyncService.process_sync(
            sync_log_id=uuid.UUID(job_id),
            tenant_id=tenant.id,
            tenant_config={},
            _session_factory=_factory,
        )

        status = await client.get(
            f"/api/v1/integrations/upload/{job_id}/status",
            headers=auth_headers,
        )
        assert status.status_code == 200


class TestDownloadTemplate:
    @pytest.mark.asyncio
    async def test_returns_csv_template(self, client: AsyncClient, auth_headers: dict):
        resp = await client.get("/api/v1/integrations/template", headers=auth_headers)
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert "SKU Code" in resp.text
        assert "Product Name" in resp.text
        assert "EXAMPLE-001" in resp.text

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client: AsyncClient):
        resp = await client.get("/api/v1/integrations/template")
        assert resp.status_code == 401
