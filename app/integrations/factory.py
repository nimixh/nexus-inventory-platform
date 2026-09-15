"""Connector registry — maps ERP types to connector classes."""

from collections.abc import Callable
from typing import TypeVar

from app.integrations.base import BaseERPConnector

T = TypeVar("T", bound=BaseERPConnector)


class ConnectorFactory:
    """Decorator-based registry for ERP connectors.

    Usage:
        @ConnectorFactory.register("csv")
        class CSVConnector(BaseERPConnector):
            ...

        connector = ConnectorFactory.get("csv", config)
    """

    _registry: dict[str, type[BaseERPConnector]] = {}

    @classmethod
    def register(cls, erp_type: str) -> Callable[[type[T]], type[T]]:
        """Decorator to register a connector class for a given erp_type."""

        def wrapper(connector_cls: type[T]) -> type[T]:
            cls._registry[erp_type] = connector_cls
            return connector_cls

        return wrapper

    @classmethod
    def get(cls, erp_type: str, config: dict) -> BaseERPConnector:
        """Return a configured connector instance for the given erp_type."""
        connector_cls = cls._registry.get(erp_type)
        if connector_cls is None:
            supported = ", ".join(sorted(cls._registry.keys()))
            raise ValueError(f"Unknown ERP type: {erp_type!r}. Supported: {supported}")
        return connector_cls(config=config)
