"""Celery tasks for ERP data sync."""

import asyncio
import logging
import uuid

from app.celery_app import celery_app
from app.services.sync import SyncService

logger = logging.getLogger(__name__)


async def _run_sync(
    sync_log_id: str,
    tenant_id: str,
    tenant_config: dict,
) -> None:
    """Async wrapper that calls the sync service."""
    await SyncService.process_sync(
        sync_log_id=uuid.UUID(sync_log_id),
        tenant_id=uuid.UUID(tenant_id),
        tenant_config=tenant_config,
    )


@celery_app.task(
    name="sync_erp_data",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def sync_erp_data(
    self,
    sync_log_id: str,
    tenant_id: str,
    tenant_config: dict,
) -> None:
    """Celery task — runs async sync logic via asyncio.run().

    Args:
        sync_log_id: UUID string of the SyncLog record
        tenant_id: UUID string of the tenant
        tenant_config: Tenant.config dict (contains csv_mappings, etc.)
    """
    try:
        asyncio.run(_run_sync(sync_log_id, tenant_id, tenant_config))
    except Exception as exc:
        logger.exception(
            "sync_erp_data failed for SyncLog %s (attempt %s/%s)",
            sync_log_id,
            self.request.retries + 1,
            self.max_retries + 1,
        )
        if self.request.retries >= self.max_retries:
            asyncio.run(
                SyncService.delete_upload(
                    sync_log_id=uuid.UUID(sync_log_id),
                    tenant_id=uuid.UUID(tenant_id),
                )
            )
            raise
        # Retry with exponential backoff (30s, 60s, 120s).
        countdown = self.default_retry_delay * (2**self.request.retries)
        raise self.retry(exc=exc, countdown=countdown)
