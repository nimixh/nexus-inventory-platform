"""Integration endpoints — file upload, sync status, CSV template.

All endpoints are registered at /api/v1/integrations.
OpenAPI docs available at /docs when the app is running.
"""

import csv
import io
import uuid
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_admin_db
from app.dependencies.auth import CurrentUser, RequireRole
from app.models.enums import UserRole
from app.models.sync_log import SyncLog
from app.repositories.tenant import get_tenant_by_id
from app.schemas.integration import JobStatusResponse, UploadResponse
from app.services.sync import SyncService
from app.tasks.sync import sync_erp_data

router = APIRouter(prefix="/integrations", tags=["Integrations"])

ALLOWED_EXTENSIONS = {".csv", ".xlsx"}


@router.post(
    "/upload",
    status_code=status.HTTP_201_CREATED,
    response_model=UploadResponse,
    summary="Upload CSV/Excel for sync",
    response_description="Job created — poll /upload/{job_id}/status for progress.",
    responses={
        400: {"description": "Unsupported file type or empty file"},
        413: {"description": "File exceeds size limit"},
    },
    dependencies=[Depends(RequireRole(UserRole.OWNER, UserRole.ADMIN, UserRole.OPS))],
)
async def upload_file(
    current_user: CurrentUser,
    file: Annotated[
        UploadFile,
        File(
            description="CSV (.csv) or Excel (.xlsx) file. Select entity_type "
            "and adjust the column names below to match the uploaded file."
        ),
    ],
    db: Annotated[AsyncSession, Depends(get_admin_db)],
    entity_type: Annotated[
        Literal["products", "transactions", "batches"],
        Form(description="Which centralized entity this upload contains."),
    ] = "products",
    product_sku_code_column: Annotated[str, Form()] = "SKU Code",
    product_name_column: Annotated[str, Form()] = "Product Name",
    product_category_column: Annotated[str, Form()] = "Category",
    product_unit_of_measure_column: Annotated[str, Form()] = "UOM",
    product_unit_cost_column: Annotated[str, Form()] = "Unit Cost",
    product_selling_price_column: Annotated[str, Form()] = "Selling Price",
    transaction_sku_code_column: Annotated[str, Form()] = "SKU Code",
    transaction_location_column: Annotated[str, Form()] = "Location",
    transaction_type_column: Annotated[str, Form()] = "Transaction Type",
    transaction_quantity_column: Annotated[str, Form()] = "Quantity",
    transaction_unit_cost_column: Annotated[str, Form()] = "Unit Cost",
    transaction_reference_column: Annotated[str, Form()] = "Reference No",
    transaction_date_column: Annotated[str, Form()] = "Transaction Date",
    batch_sku_code_column: Annotated[str, Form()] = "SKU Code",
    batch_no_column: Annotated[str, Form()] = "Batch No",
    batch_manufactured_date_column: Annotated[str, Form()] = "MFD",
    batch_expiry_date_column: Annotated[str, Form()] = "EXP",
    batch_quantity_column: Annotated[str, Form()] = "Quantity",
    batch_location_column: Annotated[str, Form()] = "Location",
) -> UploadResponse:
    """Upload a CSV or Excel file for product sync and start a background job.

    The file is saved locally and a Celery worker picks up the sync task.
    Use the returned `job_id` to poll `GET /upload/{job_id}/status` for progress.
    """
    settings = get_settings()
    filename = file.filename or "upload"

    ext = filename.lower()[filename.rfind(".") :] if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file",
        )

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {settings.MAX_UPLOAD_SIZE_MB}MB limit",
        )

    tenant = await get_tenant_by_id(db, current_user.tenant_id)
    tenant_config = tenant.config if tenant and tenant.config else {}
    upload_config = {
        **tenant_config,
        "entity_type": entity_type,
        "csv_mappings": {
            **tenant_config.get("csv_mappings", {}),
            entity_type: _csv_mapping_from_form(
                entity_type=entity_type,
                product_sku_code_column=product_sku_code_column,
                product_name_column=product_name_column,
                product_category_column=product_category_column,
                product_unit_of_measure_column=product_unit_of_measure_column,
                product_unit_cost_column=product_unit_cost_column,
                product_selling_price_column=product_selling_price_column,
                transaction_sku_code_column=transaction_sku_code_column,
                transaction_location_column=transaction_location_column,
                transaction_type_column=transaction_type_column,
                transaction_quantity_column=transaction_quantity_column,
                transaction_unit_cost_column=transaction_unit_cost_column,
                transaction_reference_column=transaction_reference_column,
                transaction_date_column=transaction_date_column,
                batch_sku_code_column=batch_sku_code_column,
                batch_no_column=batch_no_column,
                batch_manufactured_date_column=batch_manufactured_date_column,
                batch_expiry_date_column=batch_expiry_date_column,
                batch_quantity_column=batch_quantity_column,
                batch_location_column=batch_location_column,
            ),
        },
    }

    sync_service = SyncService(db)
    sync_log = await sync_service.start_sync(
        tenant_id=current_user.tenant_id,
        filename=filename,
        content=content,
    )

    sync_erp_data.delay(
        sync_log_id=str(sync_log.id),
        tenant_id=str(current_user.tenant_id),
        tenant_config=upload_config,
    )

    return UploadResponse(
        job_id=str(sync_log.id),
        status=str(sync_log.status),
    )


def _csv_mapping_from_form(
    *,
    entity_type: str,
    product_sku_code_column: str,
    product_name_column: str,
    product_category_column: str,
    product_unit_of_measure_column: str,
    product_unit_cost_column: str,
    product_selling_price_column: str,
    transaction_sku_code_column: str,
    transaction_location_column: str,
    transaction_type_column: str,
    transaction_quantity_column: str,
    transaction_unit_cost_column: str,
    transaction_reference_column: str,
    transaction_date_column: str,
    batch_sku_code_column: str,
    batch_no_column: str,
    batch_manufactured_date_column: str,
    batch_expiry_date_column: str,
    batch_quantity_column: str,
    batch_location_column: str,
) -> dict[str, str]:
    if entity_type == "transactions":
        return {
            "sku_code": transaction_sku_code_column,
            "location_name": transaction_location_column,
            "transaction_type": transaction_type_column,
            "quantity": transaction_quantity_column,
            "unit_cost_paise": transaction_unit_cost_column,
            "reference_no": transaction_reference_column,
            "transaction_date": transaction_date_column,
        }
    if entity_type == "batches":
        return {
            "sku_code": batch_sku_code_column,
            "batch_no": batch_no_column,
            "manufactured_date": batch_manufactured_date_column,
            "expiry_date": batch_expiry_date_column,
            "quantity": batch_quantity_column,
            "location_name": batch_location_column,
        }
    return {
        "sku_code": product_sku_code_column,
        "name": product_name_column,
        "category": product_category_column,
        "unit_of_measure": product_unit_of_measure_column,
        "unit_cost_paise": product_unit_cost_column,
        "selling_price_paise": product_selling_price_column,
    }


@router.get(
    "/upload/{job_id}/status",
    response_model=JobStatusResponse,
    summary="Poll sync job status",
    response_description="Current state of the sync job including progress and errors.",
    responses={
        404: {"description": "Job not found or belongs to another tenant"},
    },
)
async def upload_status(
    job_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_admin_db)],
) -> JobStatusResponse:
    """Poll the status of a previously submitted upload/sync job.

    Returns progress counters, any per-row errors (last 50), and a
    data quality score (0–100) once the job completes.
    """
    sync_log = await db.get(SyncLog, job_id)

    if sync_log is None or sync_log.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    errors = sync_log.errors or []
    return JobStatusResponse(
        job_id=str(sync_log.id),
        status=str(sync_log.status),
        records_processed=sync_log.records_processed,
        records_failed=sync_log.records_failed,
        total_records=sync_log.total_records,
        errors=errors[-50:],
        data_quality_score=sync_log.data_quality_score,
        started_at=sync_log.started_at.isoformat() if sync_log.started_at else None,
        completed_at=(
            sync_log.completed_at.isoformat() if sync_log.completed_at else None
        ),
    )


@router.get(
    "/template",
    summary="Download CSV template",
    response_description=(
        "CSV file with the exact headers expected by the upload endpoint."
    ),
    responses={
        200: {
            "description": "CSV template file",
            "content": {"text/csv": {}},
        },
    },
)
async def download_template(
    current_user: CurrentUser,
) -> Response:
    """Download a CSV template with the exact column headers and one example row.

    Fill in your product data using these column names and upload to
    `POST /upload`. The `Unit Cost` and `Selling Price` columns are in rupees
    (e.g., `100.00`) — they are automatically converted to paise during sync.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "SKU Code",
            "Product Name",
            "Category",
            "UOM",
            "Unit Cost",
            "Selling Price",
        ]
    )
    writer.writerow(
        [
            "EXAMPLE-001",
            "Sample Product",
            "General",
            "pcs",
            "100.00",
            "150.00",
        ]
    )

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=nexus-inventory-products.csv"
        },
    )
