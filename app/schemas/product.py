"""Product API schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ProductResponse(BaseModel):
    """A product as returned by the API."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    sku_code: str
    name: str
    category: str | None = None
    unit_of_measure: str
    unit_cost_paise: int
    selling_price_paise: int
    industry_attributes: dict | None = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProductListResponse(BaseModel):
    """Paginated list of products."""

    items: list[ProductResponse]
    total: int
