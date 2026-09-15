"""Unit tests for ConnectorFactory."""

import pytest

from app.integrations.base import BaseERPConnector
from app.integrations.factory import ConnectorFactory


class MockConnector(BaseERPConnector):
    def __init__(self, config: dict) -> None:
        self.config = config

    async def validate_connection(self) -> bool:
        return True

    async def fetch_products(self):
        return
        yield

    async def fetch_inventory(self):
        return
        yield

    async def fetch_transactions(self):
        return
        yield

    async def fetch_batches(self):
        return
        yield


class TestConnectorFactory:
    def setup_method(self):
        # Ensure clean state — only remove mock, never csv
        ConnectorFactory._registry.pop("mock", None)

    def test_register_and_get(self):
        @ConnectorFactory.register("mock")
        class TestConnector(MockConnector):
            pass

        connector = ConnectorFactory.get("mock", {"key": "value"})
        assert isinstance(connector, TestConnector)
        assert connector.config == {"key": "value"}

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown ERP type"):
            ConnectorFactory.get("nonexistent", {})

    def test_csv_connector_is_registered(self):
        connector = ConnectorFactory.get("csv", {"file_path": "/tmp/test.csv"})
        assert isinstance(connector, BaseERPConnector)
