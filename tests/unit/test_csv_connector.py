"""Unit tests for CSVConnector."""

import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from app.integrations.csv_connector import CSVConnector


@pytest.fixture
def sample_csv() -> Generator[Path]:
    content = (
        "SKU Code,Product Name,Category,UOM,Unit Cost,Selling Price\n"
        "SKU-001,Widget,Tools,pcs,100.00,150.00\n"
        "SKU-002,Gadget,Electronics,pcs,200.50,350.75\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(content)
    yield Path(f.name)
    Path(f.name).unlink(missing_ok=True)


@pytest.fixture
def connector(sample_csv):
    return CSVConnector(
        config={
            "file_path": str(sample_csv),
            "mappings": {
                "products": {
                    "sku_code": "SKU Code",
                    "name": "Product Name",
                    "category": "Category",
                    "unit_of_measure": "UOM",
                    "unit_cost_paise": "Unit Cost",
                    "selling_price_paise": "Selling Price",
                }
            },
        }
    )


class TestCSVConnector:
    @pytest.mark.asyncio
    async def test_validate_connection_existing_file(self, connector):
        assert await connector.validate_connection() is True

    @pytest.mark.asyncio
    async def test_validate_connection_missing_file(self):
        connector = CSVConnector(config={"file_path": "/nonexistent/path.csv"})
        assert await connector.validate_connection() is False

    @pytest.mark.asyncio
    async def test_fetch_products(self, connector):
        products = []
        async for p in connector.fetch_products():
            products.append(p)

        assert len(products) == 2
        assert products[0].sku_code == "SKU-001"
        assert products[0].name == "Widget"
        assert products[0].category == "Tools"
        assert products[0].unit_of_measure == "pcs"
        assert products[0].unit_cost_paise == 10000  # 100.00 -> 10000 paise
        assert products[0].selling_price_paise == 15000

        assert products[1].sku_code == "SKU-002"
        assert products[1].name == "Gadget"

    @pytest.mark.asyncio
    async def test_fetch_inventory_returns_empty(self, connector):
        results = []
        async for r in connector.fetch_inventory():
            results.append(r)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_fetch_transactions_returns_empty(self, connector):
        results = []
        async for r in connector.fetch_transactions():
            results.append(r)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_fetch_batches_returns_empty(self, connector):
        results = []
        async for r in connector.fetch_batches():
            results.append(r)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_default_mapping(self, sample_csv):
        """Without mappings config, uses default column headers."""
        connector = CSVConnector(config={"file_path": str(sample_csv)})
        products = []
        async for p in connector.fetch_products():
            products.append(p)
        assert len(products) == 2
        assert products[0].sku_code == "SKU-001"


class TestCSVEdgeCases:
    """Edge cases that the original implementation missed."""

    @pytest.mark.asyncio
    async def test_utf8_bom(self):
        content = (
            "﻿SKU Code,Product Name,Category,UOM,Unit Cost,Selling Price\n"
            "SKU-001,Widget,Tools,pcs,100.00,150.00\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
        path = Path(f.name)
        try:
            connector = CSVConnector(config={"file_path": str(path)})
            products = []
            async for p in connector.fetch_products():
                products.append(p)
            assert len(products) == 1
            assert products[0].sku_code == "SKU-001"
        finally:
            path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_semicolon_delimiter(self):
        content = (
            "SKU Code;Product Name;Category;UOM;Unit Cost;Selling Price\n"
            "SKU-001;Widget;Tools;pcs;100.00;150.00\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(content)
        path = Path(f.name)
        try:
            connector = CSVConnector(
                config={
                    "file_path": str(path),
                    "delimiter": ";",
                }
            )
            products = []
            async for p in connector.fetch_products():
                products.append(p)
            assert len(products) == 1
            assert products[0].sku_code == "SKU-001"
        finally:
            path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_malformed_numeric_fields(self):
        content = (
            "SKU Code,Product Name,Category,UOM,Unit Cost,Selling Price\n"
            'SKU-001,Widget,Tools,pcs,abc,"12,345.67"\n'
            'SKU-002,Gadget,Elec,pcs,"",""\n'
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(content)
        path = Path(f.name)
        try:
            connector = CSVConnector(config={"file_path": str(path)})
            products = []
            async for p in connector.fetch_products():
                products.append(p)
            assert len(products) == 2
            # "abc" -> 0
            assert products[0].unit_cost_paise == 0
            # "12,345.67" -> 1234567
            assert products[0].selling_price_paise == 1234567
            # Empty string -> 0
            assert products[1].unit_cost_paise == 0
            assert products[1].selling_price_paise == 0
        finally:
            path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_empty_file_headers_only(self):
        content = "SKU Code,Product Name,Category,UOM,Unit Cost,Selling Price\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(content)
        path = Path(f.name)
        try:
            connector = CSVConnector(config={"file_path": str(path)})
            products = []
            async for p in connector.fetch_products():
                products.append(p)
            assert len(products) == 0
        finally:
            path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_missing_required_column(self):
        """CSV without 'SKU Code' — connector defaults to empty string for sku_code."""
        content = (
            "Product Name,Category,UOM,Unit Cost,Selling Price\n"
            "Widget,Tools,pcs,100.00,150.00\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(content)
        path = Path(f.name)
        try:
            connector = CSVConnector(config={"file_path": str(path)})
            products = []
            async for p in connector.fetch_products():
                products.append(p)
            # sku_code defaults to "" via setdefault, normalize_product will
            # reject it — but the connector itself still yields the product
            assert len(products) == 1
            assert products[0].sku_code == ""
            assert products[0].name == "Widget"
        finally:
            path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_excel_file(self):
        pytest.importorskip("openpyxl")
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws.append(
            [
                "SKU Code",
                "Product Name",
                "Category",
                "UOM",
                "Unit Cost",
                "Selling Price",
            ]
        )
        ws.append(["SKU-001", "Widget", "Tools", "pcs", 100.00, 150.00])

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            wb.save(f.name)
        path = Path(f.name)
        try:
            connector = CSVConnector(config={"file_path": str(path)})
            products = []
            async for p in connector.fetch_products():
                products.append(p)
            assert len(products) == 1
            assert products[0].sku_code == "SKU-001"
            assert products[0].name == "Widget"
            assert products[0].unit_cost_paise == 10000
            assert products[0].selling_price_paise == 15000
        finally:
            path.unlink(missing_ok=True)
