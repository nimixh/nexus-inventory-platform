"""Domain enums shared across models, schemas, and services."""

from enum import StrEnum


class UserRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    OPS = "ops"
    VIEWER = "viewer"


class LocationType(StrEnum):
    WAREHOUSE = "warehouse"
    BRANCH = "branch"
    STORE = "store"


class TransactionType(StrEnum):
    IN = "in"
    OUT = "out"
    TRANSFER = "transfer"
    RETURN = "return"
    ADJUSTMENT = "adjustment"


class SyncStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SyncConnectorType(StrEnum):
    CSV = "csv"
