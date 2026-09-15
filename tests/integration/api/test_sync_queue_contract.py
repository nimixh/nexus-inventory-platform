"""Celery queue contract test — verifies the upload endpoint dispatches
sync_erp_data.delay with the correct payload shape.
"""

import csv
import io
import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient


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


class TestSyncQueueContract:
    @pytest.mark.asyncio
    async def test_upload_enqueues_celery_task(
        self, client: AsyncClient, ops_auth_headers: dict
    ):
        content = _make_csv([VALID_HEADERS, VALID_ROW])
        with patch("app.tasks.sync.sync_erp_data.delay") as mock_delay:
            resp = await client.post(
                "/api/v1/integrations/upload",
                files={"file": ("products.csv", content, "text/csv")},
                headers=ops_auth_headers,
            )

        assert resp.status_code == 201
        mock_delay.assert_called_once()

        call_kwargs = mock_delay.call_args.kwargs
        assert "sync_log_id" in call_kwargs
        assert "tenant_id" in call_kwargs
        assert "tenant_config" in call_kwargs

        # Verify UUIDs are parseable
        job_id = uuid.UUID(call_kwargs["sync_log_id"])
        tenant_id = uuid.UUID(call_kwargs["tenant_id"])
        assert job_id
        assert tenant_id
