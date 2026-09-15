"""DataNormalizer — validates, deduplicates, and persists connector output.

Key responsibilities:
- Field validation and NormalizationError per bad row (never fail entire sync)
- Unit conversion placeholder (extensible)
- Date parsing from multiple formats
- Monetary value conversion to paise (integer)
- Product deduplication via upsert on (tenant_id, sku_code)
- Location auto-creation on first reference
- Foreign key resolution (sku_code -> product_id, location_name -> location_id)
"""

import re
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.batch import Batch
from app.models.location import Location
from app.models.product import Product
from app.models.transaction import Transaction
from app.schemas.integration import (
    NormalizedBatch,
    NormalizedInventoryRecord,
    NormalizedProduct,
    NormalizedTransaction,
)


class NormalizationError(ValueError):
    """Raised when a single record cannot be normalized.

    The caller catches this, logs to SyncLog.errors, and continues
    to the next record. Never fail the entire sync for one bad row.
    """


class DataNormalizer:
    """Validates connector output and writes to the database.

    Instantiated per sync job. Caches product and location lookups
    in memory to avoid N+1 queries during bulk processing.
    """

    def __init__(self, db: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self._product_cache: dict[str, Product] = {}
        self._location_cache: dict[str, Location] = {}

    # ── public normalize methods ──────────────────────────────────────

    async def normalize_product(self, row: dict, mapping: dict) -> NormalizedProduct:
        """Apply column mapping and validate. Raises NormalizationError on failure."""
        mapped = self._apply_mapping(row, mapping)

        sku_code = mapped.get("sku_code")
        if not sku_code:
            raise NormalizationError("Missing required field: sku_code")

        name = mapped.get("name")
        if not name:
            raise NormalizationError("Missing required field: name")

        uom = mapped.get("unit_of_measure") or "pcs"

        try:
            return NormalizedProduct(
                sku_code=str(sku_code).strip(),
                name=str(name).strip(),
                category=str(category).strip()
                if (category := mapped.get("category"))
                else None,
                unit_of_measure=str(uom).strip(),
                unit_cost_paise=self._to_paise(mapped.get("unit_cost_paise", 0)),
                selling_price_paise=self._to_paise(
                    mapped.get("selling_price_paise", 0)
                ),
                industry_attributes=mapped.get("industry_attributes") or {},
            )
        except (ValueError, TypeError) as exc:
            raise NormalizationError(str(exc)) from exc

    async def normalize_inventory(
        self, row: dict, mapping: dict
    ) -> NormalizedInventoryRecord:
        mapped = self._apply_mapping(row, mapping)

        sku_code = mapped.get("sku_code")
        if not sku_code:
            raise NormalizationError("Missing required field: sku_code")

        location_name = mapped.get("location_name")
        if not location_name:
            raise NormalizationError("Missing required field: location_name")

        try:
            quantity = self._to_int(mapped.get("quantity", 0))
        except (ValueError, TypeError) as exc:
            raise NormalizationError(f"Invalid quantity: {exc}") from exc

        return NormalizedInventoryRecord(
            sku_code=str(sku_code).strip(),
            quantity=quantity,
            location_name=str(location_name).strip(),
            batch_no=str(batch).strip() if (batch := mapped.get("batch_no")) else None,
            unit_cost_paise=self._to_paise(mapped.get("unit_cost_paise", 0)),
        )

    async def normalize_transaction(
        self, row: dict, mapping: dict
    ) -> NormalizedTransaction:
        mapped = self._apply_mapping(row, mapping)

        sku_code = mapped.get("sku_code")
        if not sku_code:
            raise NormalizationError("Missing required field: sku_code")

        location_name = mapped.get("location_name")
        if not location_name:
            raise NormalizationError("Missing required field: location_name")

        txn_date = mapped.get("transaction_date")
        if txn_date is None:
            raise NormalizationError("Missing required field: transaction_date")

        try:
            parsed_date = self._parse_datetime(txn_date)
        except (ValueError, TypeError) as exc:
            raise NormalizationError(f"Invalid transaction_date: {exc}") from exc

        txn_type = mapped.get("transaction_type", "in")

        from app.models.enums import TransactionType as TT

        try:
            tt = TT(str(txn_type).strip().lower())
        except ValueError:
            raise NormalizationError(f"Invalid transaction_type: {txn_type!r}")

        try:
            quantity = self._to_int(mapped.get("quantity", 0))
        except (ValueError, TypeError) as exc:
            raise NormalizationError(f"Invalid quantity: {exc}") from exc

        return NormalizedTransaction(
            sku_code=str(sku_code).strip(),
            location_name=str(location_name).strip(),
            transaction_type=tt,
            quantity=quantity,
            unit_cost_paise=self._to_paise(mapped.get("unit_cost_paise", 0)),
            reference_no=str(ref).strip()
            if (ref := mapped.get("reference_no"))
            else None,
            transaction_date=parsed_date,
        )

    async def normalize_batch(self, row: dict, mapping: dict) -> NormalizedBatch:
        mapped = self._apply_mapping(row, mapping)

        sku_code = mapped.get("sku_code")
        if not sku_code:
            raise NormalizationError("Missing required field: sku_code")

        batch_no = mapped.get("batch_no")
        if not batch_no:
            raise NormalizationError("Missing required field: batch_no")

        mfg = mapped.get("manufactured_date")
        exp = mapped.get("expiry_date")

        try:
            quantity = self._to_int(mapped.get("quantity", 0))
        except (ValueError, TypeError) as exc:
            raise NormalizationError(f"Invalid quantity: {exc}") from exc

        return NormalizedBatch(
            sku_code=str(sku_code).strip(),
            batch_no=str(batch_no).strip(),
            manufactured_date=self._parse_date(mfg) if mfg else None,
            expiry_date=self._parse_date(exp) if exp else None,
            quantity=quantity,
            location_name=str(loc).strip()
            if (loc := mapped.get("location_name"))
            else None,
        )

    # ── upsert methods ────────────────────────────────────────────────

    async def upsert_product(self, normalized: NormalizedProduct) -> Product:
        """Insert or update product on (tenant_id, sku_code) match."""
        stmt = (
            insert(Product)
            .values(
                tenant_id=self.tenant_id,
                sku_code=normalized.sku_code,
                name=normalized.name,
                category=normalized.category,
                unit_of_measure=normalized.unit_of_measure,
                unit_cost_paise=normalized.unit_cost_paise,
                selling_price_paise=normalized.selling_price_paise,
                industry_attributes=normalized.industry_attributes,
            )
            .on_conflict_do_update(
                constraint="uq_tenant_sku",
                set_={
                    "name": normalized.name,
                    "category": normalized.category,
                    "unit_of_measure": normalized.unit_of_measure,
                    "unit_cost_paise": normalized.unit_cost_paise,
                    "selling_price_paise": normalized.selling_price_paise,
                    "industry_attributes": normalized.industry_attributes,
                    "updated_at": func.now(),
                },
            )
            .returning(Product)
        )
        result = await self.db.execute(stmt)
        product = result.scalar_one()
        await self.db.flush()
        self._product_cache[normalized.sku_code] = product
        return product

    async def upsert_inventory(
        self,
        record: NormalizedInventoryRecord,
        product: Product,
        location: Location,
    ) -> None:
        """Write inventory as an 'in' transaction."""
        from app.models.enums import TransactionType

        txn = Transaction(
            tenant_id=self.tenant_id,
            product_id=product.id,
            location_id=location.id,
            transaction_type=TransactionType.IN,
            quantity=record.quantity,
            unit_cost_paise=record.unit_cost_paise,
            transaction_date=datetime.now(UTC),
        )
        self.db.add(txn)
        await self.db.flush()

    async def create_transaction(
        self, normalized: NormalizedTransaction
    ) -> Transaction:
        """Insert a transaction after resolving product and location references."""
        product = await self._resolve_product(normalized.sku_code)
        location = await self._resolve_location(normalized.location_name)
        existing_stmt = select(Transaction).where(
            Transaction.tenant_id == self.tenant_id,
            Transaction.product_id == product.id,
            Transaction.location_id == location.id,
            Transaction.transaction_type == normalized.transaction_type,
            Transaction.quantity == normalized.quantity,
            Transaction.unit_cost_paise == normalized.unit_cost_paise,
            Transaction.reference_no == normalized.reference_no,
            Transaction.transaction_date == normalized.transaction_date,
        )
        existing = await self.db.execute(existing_stmt)
        if transaction := existing.scalar_one_or_none():
            return transaction

        txn = Transaction(
            tenant_id=self.tenant_id,
            product_id=product.id,
            location_id=location.id,
            transaction_type=normalized.transaction_type,
            quantity=normalized.quantity,
            unit_cost_paise=normalized.unit_cost_paise,
            reference_no=normalized.reference_no,
            transaction_date=normalized.transaction_date,
        )
        self.db.add(txn)
        await self.db.flush()
        return txn

    async def upsert_batch(self, normalized: NormalizedBatch) -> Batch:
        """Insert or update a batch on (tenant_id, batch_no, product_id)."""
        product = await self._resolve_product(normalized.sku_code)
        location = (
            await self._resolve_location(normalized.location_name)
            if normalized.location_name
            else None
        )
        stmt = (
            insert(Batch)
            .values(
                tenant_id=self.tenant_id,
                product_id=product.id,
                batch_no=normalized.batch_no,
                manufactured_date=normalized.manufactured_date,
                expiry_date=normalized.expiry_date,
                quantity=normalized.quantity,
                location_id=location.id if location else None,
            )
            .on_conflict_do_update(
                constraint="uq_tenant_batch_product",
                set_={
                    "manufactured_date": normalized.manufactured_date,
                    "expiry_date": normalized.expiry_date,
                    "quantity": normalized.quantity,
                    "location_id": location.id if location else None,
                    "updated_at": func.now(),
                },
            )
            .returning(Batch)
        )
        result = await self.db.execute(stmt)
        batch = result.scalar_one()
        await self.db.flush()
        return batch

    # ── resolution helpers ────────────────────────────────────────────

    async def _resolve_product(self, sku_code: str) -> Product:
        """Lookup a product by sku_code within the tenant. Caches per instance."""
        if sku_code in self._product_cache:
            return self._product_cache[sku_code]

        stmt = select(Product).where(
            Product.tenant_id == self.tenant_id,
            Product.sku_code == sku_code,
        )
        result = await self.db.execute(stmt)
        product = result.scalar_one_or_none()
        if product is None:
            raise NormalizationError(f"Product with sku_code {sku_code!r} not found")
        self._product_cache[sku_code] = product
        return product

    async def _resolve_location(self, name: str) -> Location:
        """Lookup a location by name within the tenant, or auto-create."""
        if name in self._location_cache:
            return self._location_cache[name]

        stmt = select(Location).where(
            Location.tenant_id == self.tenant_id,
            Location.name == name,
        )
        result = await self.db.execute(stmt)
        location = result.scalar_one_or_none()
        if location is None:
            location = Location(
                tenant_id=self.tenant_id,
                name=name,
            )
            self.db.add(location)
            await self.db.flush()
        self._location_cache[name] = location
        return location

    # ── static conversion helpers ─────────────────────────────────────

    @staticmethod
    def _to_paise(value: str | float | int | None) -> int:
        """Convert a monetary value to paise (integer).

        Handles:
        - float: 100.50 -> 10050
        - string: "1,234.56" -> 123456
        - int: 10000 (already paise) — passed through
        - None / empty: 0
        """
        if value is None:
            return 0
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(round(value * 100))
        if isinstance(value, str):
            cleaned = value.replace(",", "").strip()
            if not cleaned:
                return 0
            return int(round(float(cleaned) * 100))
        return 0

    @staticmethod
    def _to_int(value: str | float | int | None) -> int:
        """Convert a numeric value to int. Handles strings with commas."""
        if value is None:
            return 0
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            cleaned = value.replace(",", "").strip()
            if not cleaned:
                return 0
            return int(float(cleaned))
        return 0

    @staticmethod
    def _parse_date(value: str | date | None) -> date | None:
        """Parse a date from multiple common formats.

        Supports: ISO (2024-01-15), DD-MM-YYYY, MM/DD/YYYY, YYYY/MM/DD.
        """
        if value is None:
            return None
        if isinstance(value, date):
            return value
        s = str(value).strip()

        # ISO
        if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            return datetime.strptime(s, "%Y-%m-%d").date()

        # DD-MM-YYYY
        if re.match(r"^\d{2}-\d{2}-\d{4}$", s):
            return datetime.strptime(s, "%d-%m-%Y").date()

        # MM/DD/YYYY
        if re.match(r"^\d{2}/\d{2}/\d{4}$", s):
            return datetime.strptime(s, "%m/%d/%Y").date()

        # YYYY/MM/DD
        if re.match(r"^\d{4}/\d{2}/\d{2}$", s):
            return datetime.strptime(s, "%Y/%m/%d").date()

        raise ValueError(f"Unrecognized date format: {s!r}")

    @staticmethod
    def _parse_datetime(value: str | datetime | None) -> datetime:
        """Parse a datetime from string or return as-is if already datetime."""
        if value is None:
            raise ValueError("datetime value is required")
        if isinstance(value, datetime):
            return value
        s = str(value).strip()

        # ISO-8601 with T or space separator
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                return datetime.strptime(s, fmt).replace(tzinfo=UTC)
            except ValueError:
                continue

        # Try date-only, assume midnight UTC
        try:
            parsed_date = DataNormalizer._parse_date(s)
            if parsed_date is not None:
                return datetime(
                    parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=UTC
                )
        except ValueError:
            pass

        raise ValueError(f"Unrecognized datetime format: {s!r}")

    @staticmethod
    def _apply_mapping(row: dict, mapping: dict) -> dict:
        """Map CSV column names to normalized field names.

        mapping is {target_field: source_column}, e.g.:
            {"sku_code": "SKU Code", "name": "Product Name"}
        If mapping is empty, the row already uses normalized keys — return as-is.
        """
        if not mapping:
            return dict(row)
        mapped: dict[str, object] = {}
        for target_field, source_column in mapping.items():
            if source_column in row:
                mapped[target_field] = row[source_column]
        return mapped
