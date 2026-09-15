"""CSV/Excel connector — parses uploaded files and yields normalized records.

Registered as the "csv" connector type. Applies a configurable column mapping
so pilot clients can use their own CSV headers before the ERP connector is ready.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from app.integrations.base import BaseERPConnector
from app.integrations.factory import ConnectorFactory
from app.models.enums import TransactionType
from app.schemas.integration import (
    NormalizedBatch,
    NormalizedInventoryRecord,
    NormalizedProduct,
    NormalizedTransaction,
)

DEFAULT_PRODUCT_MAPPING = {
    "sku_code": "SKU Code",
    "name": "Product Name",
    "category": "Category",
    "unit_of_measure": "UOM",
    "unit_cost_paise": "Unit Cost",
    "selling_price_paise": "Selling Price",
}

DEFAULT_TRANSACTION_MAPPING = {
    "sku_code": "SKU Code",
    "location_name": "Location",
    "transaction_type": "Transaction Type",
    "quantity": "Quantity",
    "unit_cost_paise": "Unit Cost",
    "reference_no": "Reference No",
    "transaction_date": "Transaction Date",
}

DEFAULT_BATCH_MAPPING = {
    "sku_code": "SKU Code",
    "batch_no": "Batch No",
    "manufactured_date": "MFD",
    "expiry_date": "EXP",
    "quantity": "Quantity",
    "location_name": "Location",
}


@ConnectorFactory.register("csv")
class CSVConnector(BaseERPConnector):
    """Reads CSV/Excel files and produces normalized domain records.

    Config keys:
        file_path: str — path to the uploaded file
        mappings: dict — per-entity field mapping, e.g.:
            {"products": {"sku_code": "SKU", "name": "Product Name", ...}}
        delimiter: str — CSV delimiter (default ",")
        sheet_name: str | int | None — Excel sheet name/number (default 0)
    """

    def __init__(self, config: dict) -> None:
        self.file_path: str = config["file_path"]
        self.mappings: dict = config.get("mappings", {})
        self.delimiter: str = config.get("delimiter", ",")
        self.sheet_name: str | int | None = config.get("sheet_name", 0)
        self.entity_type: str = config.get("entity_type", "products")

    async def validate_connection(self) -> bool:
        return Path(self.file_path).exists()

    async def fetch_products(self) -> AsyncIterator[NormalizedProduct]:
        if self.entity_type != "products":
            return
        df = await self._read_dataframe(self.sheet_name)
        mapping = self.mappings.get("products", DEFAULT_PRODUCT_MAPPING)
        for _, row in df.iterrows():
            row_dict = row.dropna().to_dict()
            yield self._map_to_product(row_dict, mapping)

    async def fetch_inventory(self) -> AsyncIterator[NormalizedInventoryRecord]:
        return
        yield  # unreachable — makes this an async generator

    async def fetch_transactions(self) -> AsyncIterator[NormalizedTransaction]:
        if self.entity_type != "transactions":
            return
        df = await self._read_dataframe(self.sheet_name)
        mapping = self.mappings.get("transactions", DEFAULT_TRANSACTION_MAPPING)
        for _, row in df.iterrows():
            row_dict = row.dropna().to_dict()
            yield self._map_to_transaction(row_dict, mapping)

    async def fetch_batches(self) -> AsyncIterator[NormalizedBatch]:
        if self.entity_type != "batches":
            return
        df = await self._read_dataframe(self.sheet_name)
        mapping = self.mappings.get("batches", DEFAULT_BATCH_MAPPING)
        for _, row in df.iterrows():
            row_dict = row.dropna().to_dict()
            yield self._map_to_batch(row_dict, mapping)

    # ── internal ──────────────────────────────────────────────────────

    async def _read_dataframe(self, sheet_name: str | int | None = 0) -> pd.DataFrame:
        """Read CSV or Excel into a DataFrame, offloading to a thread."""
        file_path = Path(self.file_path)
        suffix = file_path.suffix.lower()

        def _read() -> pd.DataFrame:
            if suffix == ".csv":
                return pd.read_csv(file_path, sep=self.delimiter, dtype=str)
            return pd.read_excel(file_path, sheet_name=sheet_name or 0, dtype=str)

        return await asyncio.to_thread(_read)

    @staticmethod
    def _map_to_product(row: dict, mapping: dict) -> NormalizedProduct:
        """Apply column mapping and build a NormalizedProduct."""
        mapped = _apply_mapping(row, mapping)

        # Provide defaults for required fields
        mapped.setdefault("sku_code", "")
        mapped.setdefault("name", "")
        mapped.setdefault("unit_of_measure", "pcs")
        mapped.setdefault("unit_cost_paise", 0)
        mapped.setdefault("selling_price_paise", 0)

        return NormalizedProduct(
            sku_code=str(mapped["sku_code"]).strip(),
            name=str(mapped["name"]).strip(),
            category=str(mapped["category"]).strip()
            if mapped.get("category")
            else None,
            unit_of_measure=str(mapped["unit_of_measure"]).strip(),
            unit_cost_paise=_to_paise(mapped["unit_cost_paise"]),
            selling_price_paise=_to_paise(mapped["selling_price_paise"]),
        )

    @staticmethod
    def _map_to_transaction(row: dict, mapping: dict) -> NormalizedTransaction:
        """Apply column mapping and build a NormalizedTransaction."""
        mapped = _apply_mapping(row, mapping)
        return NormalizedTransaction(
            sku_code=str(mapped.get("sku_code", "")).strip(),
            location_name=str(mapped.get("location_name", "")).strip(),
            transaction_type=_to_transaction_type(
                mapped.get("transaction_type", TransactionType.IN)
            ),
            quantity=_to_int(mapped.get("quantity", 0)),
            unit_cost_paise=_to_paise(mapped.get("unit_cost_paise", 0)),
            reference_no=str(ref).strip()
            if (ref := mapped.get("reference_no"))
            else None,
            transaction_date=_to_datetime(mapped.get("transaction_date")),
        )

    @staticmethod
    def _map_to_batch(row: dict, mapping: dict) -> NormalizedBatch:
        """Apply column mapping and build a NormalizedBatch."""
        mapped = _apply_mapping(row, mapping)
        return NormalizedBatch(
            sku_code=str(mapped.get("sku_code", "")).strip(),
            batch_no=str(mapped.get("batch_no", "")).strip(),
            manufactured_date=_to_date(mapped.get("manufactured_date")),
            expiry_date=_to_date(mapped.get("expiry_date")),
            quantity=_to_int(mapped.get("quantity", 0)),
            location_name=str(loc).strip()
            if (loc := mapped.get("location_name"))
            else None,
        )


def _apply_mapping(row: dict, mapping: dict) -> dict[str, object]:
    mapped: dict[str, object] = {}
    for target_field, source_column in mapping.items():
        if source_column in row:
            val = row[source_column]
            if isinstance(val, float) and val != val:
                continue
            mapped[target_field] = val
    return mapped


def _to_paise(value: object) -> int:
    """Coerce a pandas-origin rupee value to int paise (multiply by 100)."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value != value:
            return 0
        return int(round(float(value) * 100))
    s = str(value).replace(",", "").strip()
    if not s:
        return 0
    try:
        return int(round(float(s) * 100))
    except ValueError, TypeError:
        return 0


def _to_int(value: object) -> int:
    """Coerce a pandas-origin numeric value to an integer quantity."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value != value:
            return 0
        return int(float(value))
    s = str(value).replace(",", "").strip()
    if not s:
        return 0
    try:
        return int(float(s))
    except ValueError, TypeError:
        return 0


def _to_transaction_type(value: object) -> TransactionType:
    try:
        return TransactionType(str(value).strip().lower())
    except ValueError:
        return TransactionType.IN


def _to_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _to_datetime(value: object) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    parsed_date = _to_date(value)
    if parsed_date is not None:
        return datetime(
            parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=UTC
        )
    s = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return datetime.now(UTC)
