import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin
from app.models.enums import TransactionType


class Transaction(TenantMixin, Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT")
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT")
    )
    transaction_type: Mapped[TransactionType] = mapped_column(String(50))
    quantity: Mapped[int] = mapped_column(BigInteger)
    unit_cost_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    reference_no: Mapped[str | None] = mapped_column(String(100))
    transaction_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_transactions_tenant_date", "tenant_id", transaction_date.desc()),
        Index("ix_transactions_tenant_product", "tenant_id", "product_id"),
        Index("ix_transactions_tenant_type", "tenant_id", "transaction_type"),
        Index("ix_transactions_tenant_location", "tenant_id", "location_id"),
    )
