import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    industry_type: Mapped[str | None] = mapped_column(String(100))
    erp_type: Mapped[str | None] = mapped_column(String(100))

    # Subscription
    subscription_plan: Mapped[str] = mapped_column(
        String(20), default="trial"
    )  # trial / starter / growth / enterprise
    subscription_status: Mapped[str] = mapped_column(
        String(20), default="trial"
    )  # trial / active / past_due / suspended / cancelled
    trial_start_date: Mapped[date | None] = mapped_column(Date)
    trial_end_date: Mapped[date | None] = mapped_column(Date)
    subscription_start_date: Mapped[date | None] = mapped_column(Date)
    next_billing_date: Mapped[date | None] = mapped_column(Date)

    # Config
    config: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
