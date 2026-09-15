"""Abstract base class for all ERP connectors.

Each connector produces normalized domain records using AsyncIterator
so large datasets stream without loading everything into memory.
Connectors are independent of persistence — they yield data and the
DataNormalizer handles DB writes.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.schemas.integration import (
    NormalizedBatch,
    NormalizedInventoryRecord,
    NormalizedProduct,
    NormalizedTransaction,
)


class BaseERPConnector(ABC):
    """Abstract connector that every ERP integration must implement.

    Subclasses implement these as async generators (async def + yield).
    """

    def __init__(self, config: dict) -> None:
        self.config = config

    @abstractmethod
    async def validate_connection(self) -> bool:
        """Verify connectivity / credentials are valid."""
        ...

    @abstractmethod
    def fetch_products(self) -> AsyncIterator[NormalizedProduct]:
        """Yield products from the ERP source."""
        ...

    @abstractmethod
    def fetch_inventory(self) -> AsyncIterator[NormalizedInventoryRecord]:
        """Yield current inventory records from the ERP source."""
        ...

    @abstractmethod
    def fetch_transactions(self) -> AsyncIterator[NormalizedTransaction]:
        """Yield transaction records from the ERP source."""
        ...

    @abstractmethod
    def fetch_batches(self) -> AsyncIterator[NormalizedBatch]:
        """Yield batch/lot records from the ERP source."""
        ...
