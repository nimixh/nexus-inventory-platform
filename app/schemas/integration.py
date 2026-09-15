"""Universal connector contract schemas and API response models.

The four Normalized* schemas are the output format that every ERP connector
must produce. They use human-readable identifiers (sku_code, location_name)
rather than UUIDs — the DataNormalizer resolves them to foreign keys during
persistence.

UploadResponse and JobStatusResponse are the API contracts for the
/integrations endpoints and drive the OpenAPI docs at /docs.
"""

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import TransactionType

# ── Connector output schemas (universal contract) ─────────────────────


class NormalizedProduct(BaseModel):
    """A product record as produced by any ERP connector."""

    sku_code: str
    name: str
    category: str | None = None
    unit_of_measure: str
    unit_cost_paise: int = 0
    selling_price_paise: int = 0
    industry_attributes: dict = Field(default_factory=dict)


class NormalizedInventoryRecord(BaseModel):
    """Current inventory position for a product at a location."""

    sku_code: str
    quantity: int
    location_name: str
    batch_no: str | None = None
    unit_cost_paise: int = 0


class NormalizedTransaction(BaseModel):
    """A single inventory movement (in, out, transfer, etc.)."""

    sku_code: str
    location_name: str
    transaction_type: TransactionType
    quantity: int
    unit_cost_paise: int = 0
    reference_no: str | None = None
    transaction_date: datetime


class NormalizedBatch(BaseModel):
    """Batch / lot tracking record."""

    sku_code: str
    batch_no: str
    manufactured_date: date | None = None
    expiry_date: date | None = None
    quantity: int
    location_name: str | None = None


# ── API response schemas (OpenAPI docs) ───────────────────────────────


class UploadResponse(BaseModel):
    """Returned when a file upload is accepted for processing."""

    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    """Current progress of a sync job — poll this to track completion."""

    job_id: str
    status: str
    records_processed: int
    records_failed: int
    total_records: int
    errors: list[dict] = Field(default_factory=list)
    data_quality_score: float | None = None
    started_at: str | None = None
    completed_at: str | None = None
