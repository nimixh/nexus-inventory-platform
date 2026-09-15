"""Unit tests for DataNormalizer."""

import uuid
from datetime import UTC, date, datetime

import pytest

from app.integrations.normalizer import DataNormalizer, NormalizationError


class TestToPaise:
    def test_converts_float(self):
        assert DataNormalizer._to_paise(100.50) == 10050

    def test_converts_string_with_commas(self):
        assert DataNormalizer._to_paise("1,234.56") == 123456

    def test_handles_integer_input(self):
        assert DataNormalizer._to_paise(10000) == 10000

    def test_handles_none(self):
        assert DataNormalizer._to_paise(None) == 0

    def test_handles_empty_string(self):
        assert DataNormalizer._to_paise("") == 0

    def test_handles_plain_string(self):
        assert DataNormalizer._to_paise("150.00") == 15000


class TestToInt:
    def test_converts_float(self):
        assert DataNormalizer._to_int(10.5) == 10

    def test_converts_string_with_commas(self):
        assert DataNormalizer._to_int("1,000") == 1000

    def test_handles_none(self):
        assert DataNormalizer._to_int(None) == 0

    def test_handles_empty_string(self):
        assert DataNormalizer._to_int("") == 0


class TestParseDate:
    def test_iso_format(self):
        assert DataNormalizer._parse_date("2024-01-15") == date(2024, 1, 15)

    def test_dd_mm_yyyy(self):
        assert DataNormalizer._parse_date("15-01-2024") == date(2024, 1, 15)

    def test_mm_dd_yyyy(self):
        assert DataNormalizer._parse_date("01/15/2024") == date(2024, 1, 15)

    def test_yyyy_mm_dd_slashes(self):
        assert DataNormalizer._parse_date("2024/01/15") == date(2024, 1, 15)

    def test_handles_none(self):
        assert DataNormalizer._parse_date(None) is None

    def test_handles_date_object(self):
        d = date(2024, 6, 15)
        assert DataNormalizer._parse_date(d) == d

    def test_raises_on_unknown_format(self):
        with pytest.raises(ValueError, match="Unrecognized date format"):
            DataNormalizer._parse_date("Jan 15 2024")


class TestParseDatetime:
    def test_iso_format(self):
        result = DataNormalizer._parse_datetime("2024-01-15T10:30:00")
        assert result == datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)

    def test_space_separator(self):
        result = DataNormalizer._parse_datetime("2024-01-15 10:30:00")
        assert result == datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)

    def test_date_only_assumes_midnight(self):
        result = DataNormalizer._parse_datetime("2024-06-15")
        assert result == datetime(2024, 6, 15, 0, 0, 0, tzinfo=UTC)

    def test_handles_datetime_object(self):
        dt = datetime(2024, 6, 15, tzinfo=UTC)
        assert DataNormalizer._parse_datetime(dt) == dt

    def test_raises_on_none(self):
        with pytest.raises(ValueError):
            DataNormalizer._parse_datetime(None)


class TestApplyMapping:
    def test_maps_columns(self):
        row = {"SKU Code": "ABC-001", "Product Name": "Widget"}
        mapping = {"sku_code": "SKU Code", "name": "Product Name"}
        result = DataNormalizer._apply_mapping(row, mapping)
        assert result == {"sku_code": "ABC-001", "name": "Widget"}

    def test_skips_missing_source_columns(self):
        row = {"SKU Code": "ABC-001"}
        mapping = {"sku_code": "SKU Code", "name": "Product Name"}
        result = DataNormalizer._apply_mapping(row, mapping)
        assert result == {"sku_code": "ABC-001"}


class TestNormalizeProduct:
    @pytest.fixture
    def normalizer(self):
        return DataNormalizer(db=None, tenant_id=uuid.uuid4())  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_success(self, normalizer):
        row = {
            "SKU Code": "SKU-001",
            "Product Name": "Widget",
            "Category": "Tools",
            "UOM": "pcs",
            "Unit Cost": "100.00",
            "Selling Price": "150.50",
        }
        mapping = {
            "sku_code": "SKU Code",
            "name": "Product Name",
            "category": "Category",
            "unit_of_measure": "UOM",
            "unit_cost_paise": "Unit Cost",
            "selling_price_paise": "Selling Price",
        }
        result = await normalizer.normalize_product(row, mapping)
        assert result.sku_code == "SKU-001"
        assert result.name == "Widget"
        assert result.category == "Tools"
        assert result.unit_of_measure == "pcs"
        assert result.unit_cost_paise == 10000
        assert result.selling_price_paise == 15050

    @pytest.mark.asyncio
    async def test_missing_sku_code(self, normalizer):
        row = {"Product Name": "Widget"}
        mapping = {"sku_code": "SKU Code", "name": "Product Name"}
        with pytest.raises(
            NormalizationError, match="Missing required field: sku_code"
        ):
            await normalizer.normalize_product(row, mapping)

    @pytest.mark.asyncio
    async def test_missing_name(self, normalizer):
        row = {"SKU Code": "SKU-001"}
        mapping = {"sku_code": "SKU Code", "name": "Product Name"}
        with pytest.raises(NormalizationError, match="Missing required field: name"):
            await normalizer.normalize_product(row, mapping)

    @pytest.mark.asyncio
    async def test_defaults_missing_uom(self, normalizer):
        row = {"SKU Code": "SKU-001", "Product Name": "Widget"}
        mapping = {"sku_code": "SKU Code", "name": "Product Name"}
        result = await normalizer.normalize_product(row, mapping)
        assert result.unit_of_measure == "pcs"

    @pytest.mark.asyncio
    async def test_null_cost_defaults_to_zero(self, normalizer):
        row = {
            "SKU Code": "SKU-001",
            "Product Name": "Widget",
            "Unit Cost": None,
            "Selling Price": None,
        }
        mapping = {
            "sku_code": "SKU Code",
            "name": "Product Name",
            "unit_cost_paise": "Unit Cost",
            "selling_price_paise": "Selling Price",
        }
        result = await normalizer.normalize_product(row, mapping)
        assert result.unit_cost_paise == 0
        assert result.selling_price_paise == 0

    @pytest.mark.asyncio
    async def test_normalize_product_with_empty_mapping_uses_row_keys(self, normalizer):
        """When mapping is empty, the row already has normalized field names.

        This is how process_sync calls normalize_product — the connector yields
        NormalizedProduct dataclass instances and the fields are passed directly.
        """
        row = {
            "sku_code": "SKU-001",
            "name": "Widget",
            "category": "Tools",
            "unit_of_measure": "pcs",
            "unit_cost_paise": 10000,
            "selling_price_paise": 15000,
        }
        result = await normalizer.normalize_product(row, {})
        assert result.sku_code == "SKU-001"
        assert result.name == "Widget"
        assert result.category == "Tools"
        assert result.unit_of_measure == "pcs"
        assert result.unit_cost_paise == 10000
        assert result.selling_price_paise == 15000

    @pytest.mark.asyncio
    async def test_normalize_empty_mapping_requires_sku_and_name(self, normalizer):
        row = {"unit_cost_paise": 100}
        with pytest.raises(NormalizationError, match="sku_code"):
            await normalizer.normalize_product(row, {})
        row2 = {"sku_code": "SK-1"}
        with pytest.raises(NormalizationError, match="name"):
            await normalizer.normalize_product(row2, {})
