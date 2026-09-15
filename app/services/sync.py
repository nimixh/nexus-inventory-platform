"""SyncService — orchestrates the end-to-end file sync pipeline.

Flow:
1. start_sync() — save file, create SyncLog (status=pending)
2. Celery task calls process_sync() — normalize & persist, update SyncLog
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session_factory, set_tenant_context
from app.integrations.factory import ConnectorFactory
from app.integrations.file_storage import FileStorage, LocalFileStorage
from app.integrations.normalizer import DataNormalizer, NormalizationError
from app.models.enums import SyncConnectorType, SyncStatus
from app.models.sync_log import SyncLog

logger = logging.getLogger(__name__)

DEFAULT_QUALITY_BASE = 100.0


class SyncService:
    """Orchestrates upload → normalize → persist with per-row error handling."""

    def __init__(
        self,
        db: AsyncSession,
        file_storage: FileStorage | None = None,
    ) -> None:
        self.db = db
        self.file_storage = file_storage or LocalFileStorage(
            base_dir=get_settings().UPLOAD_DIR
        )

    async def start_sync(
        self,
        tenant_id: uuid.UUID,
        filename: str,
        content: bytes,
        connector_type: str = "csv",
    ) -> SyncLog:
        """Save file and create a pending SyncLog. Returns the log for job_id."""
        stored_path = await self.file_storage.save(filename, content)

        sync_log = SyncLog(
            tenant_id=tenant_id,
            connector_type=SyncConnectorType(connector_type),
            original_filename=filename,
            stored_path=stored_path,
            status=SyncStatus.PENDING,
        )
        self.db.add(sync_log)
        await self.db.commit()
        await self.db.refresh(sync_log)
        return sync_log

    @staticmethod
    async def process_sync(
        sync_log_id: uuid.UUID,
        tenant_id: uuid.UUID,
        tenant_config: dict,
        _session_factory=async_session_factory,
    ) -> None:
        """Core sync logic — runs inside the Celery worker.

        Creates its own DB session (request session is long gone).
        Sets tenant context so RLS policies allow writes.
        Never raises on a single bad row — errors accumulate in SyncLog.errors.

        _session_factory is overridable for tests that need to share a connection.
        """
        async with _session_factory() as db:
            await set_tenant_context(db, str(tenant_id))

            sync_log = await db.get(SyncLog, sync_log_id)
            if sync_log is None:
                logger.error("SyncLog %s not found", sync_log_id)
                return

            sync_log.status = SyncStatus.RUNNING
            sync_log.started_at = datetime.now(UTC)
            await db.commit()

            file_storage = LocalFileStorage(base_dir=get_settings().UPLOAD_DIR)

            succeeded = False
            try:
                connector_config: dict[str, object] = {
                    "file_path": sync_log.stored_path or "",
                    "mappings": tenant_config.get("csv_mappings", {}),
                    "entity_type": tenant_config.get("entity_type", "products"),
                }
                connector = ConnectorFactory.get(
                    str(sync_log.connector_type), connector_config
                )
                normalizer = DataNormalizer(db, tenant_id)
                entity_type = str(tenant_config.get("entity_type", "products"))

                # ── products ──────────────────────────────────
                if entity_type == "transactions":
                    await SyncService._process_transactions(
                        connector, normalizer, sync_log
                    )
                elif entity_type == "batches":
                    await SyncService._process_batches(connector, normalizer, sync_log)
                else:
                    await SyncService._process_products(connector, normalizer, sync_log)

                # ── quality score ─────────────────────────────
                sync_log.data_quality_score = SyncService._calculate_quality(sync_log)
                sync_log.status = SyncStatus.COMPLETED
                sync_log.completed_at = datetime.now(UTC)
                await db.commit()
                succeeded = True

            except Exception:
                logger.exception("Fatal sync error for SyncLog %s", sync_log_id)
                await db.rollback()
                # Re-fetch after rollback to update status
                await db.refresh(sync_log)
                sync_log.status = SyncStatus.FAILED
                errors = sync_log.errors or []
                errors.append({"fatal": "Sync failed — see worker logs for details"})
                sync_log.errors = errors
                sync_log.completed_at = datetime.now(UTC)
                await db.commit()
                raise
            finally:
                # Failures are retried by Celery, so retain their source file.
                if succeeded and sync_log.stored_path:
                    await file_storage.delete(sync_log.stored_path)

    @staticmethod
    async def delete_upload(
        sync_log_id: uuid.UUID,
        tenant_id: uuid.UUID,
        _session_factory=async_session_factory,
    ) -> None:
        """Delete an upload after Celery exhausts all retry attempts."""
        async with _session_factory() as db:
            await set_tenant_context(db, str(tenant_id))
            sync_log = await db.get(SyncLog, sync_log_id)
            if sync_log is None or not sync_log.stored_path:
                return
            file_storage = LocalFileStorage(base_dir=get_settings().UPLOAD_DIR)
            await file_storage.delete(sync_log.stored_path)

    @staticmethod
    def _calculate_quality(sync_log: SyncLog) -> float:
        total = sync_log.records_processed + sync_log.records_failed
        if total == 0:
            return 0.0
        base = DEFAULT_QUALITY_BASE
        failure_rate = sync_log.records_failed / total
        base -= failure_rate * 50  # up to 50 points off
        return max(0.0, round(base, 1))

    @staticmethod
    async def _process_products(connector, normalizer, sync_log: SyncLog) -> None:
        async for np in connector.fetch_products():
            sync_log.total_records += 1
            try:
                validated = await normalizer.normalize_product(
                    {
                        "sku_code": np.sku_code,
                        "name": np.name,
                        "category": np.category,
                        "unit_of_measure": np.unit_of_measure,
                        "unit_cost_paise": np.unit_cost_paise,
                        "selling_price_paise": np.selling_price_paise,
                        "industry_attributes": np.industry_attributes,
                    },
                    {},
                )
                await normalizer.upsert_product(validated)
                sync_log.records_processed += 1
            except NormalizationError as exc:
                SyncService._append_row_error(sync_log, "product", np, exc)
            except Exception:
                sync_log.records_failed += 1
                logger.exception("Unexpected error processing product row")

    @staticmethod
    async def _process_transactions(connector, normalizer, sync_log: SyncLog) -> None:
        async for txn in connector.fetch_transactions():
            sync_log.total_records += 1
            try:
                validated = await normalizer.normalize_transaction(
                    {
                        "sku_code": txn.sku_code,
                        "location_name": txn.location_name,
                        "transaction_type": txn.transaction_type,
                        "quantity": txn.quantity,
                        "unit_cost_paise": txn.unit_cost_paise,
                        "reference_no": txn.reference_no,
                        "transaction_date": txn.transaction_date,
                    },
                    {},
                )
                await normalizer.create_transaction(validated)
                sync_log.records_processed += 1
            except NormalizationError as exc:
                SyncService._append_row_error(sync_log, "transaction", txn, exc)
            except Exception:
                sync_log.records_failed += 1
                logger.exception("Unexpected error processing transaction row")

    @staticmethod
    async def _process_batches(connector, normalizer, sync_log: SyncLog) -> None:
        async for batch in connector.fetch_batches():
            sync_log.total_records += 1
            try:
                validated = await normalizer.normalize_batch(
                    {
                        "sku_code": batch.sku_code,
                        "batch_no": batch.batch_no,
                        "manufactured_date": batch.manufactured_date,
                        "expiry_date": batch.expiry_date,
                        "quantity": batch.quantity,
                        "location_name": batch.location_name,
                    },
                    {},
                )
                await normalizer.upsert_batch(validated)
                sync_log.records_processed += 1
            except NormalizationError as exc:
                SyncService._append_row_error(sync_log, "batch", batch, exc)
            except Exception:
                sync_log.records_failed += 1
                logger.exception("Unexpected error processing batch row")

    @staticmethod
    def _append_row_error(
        sync_log: SyncLog, entity: str, record: object, exc: Exception
    ) -> None:
        sync_log.records_failed += 1
        errors = sync_log.errors or []
        errors.append(
            {
                "entity": entity,
                "sku_code": getattr(record, "sku_code", "?"),
                "error": str(exc),
            }
        )
        sync_log.errors = errors
