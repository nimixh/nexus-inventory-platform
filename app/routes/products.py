"""Product endpoints — tenant-scoped product listing."""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.dependencies.auth import TenantSessionDep
from app.models.product import Product
from app.schemas.product import ProductListResponse, ProductResponse

router = APIRouter(prefix="/products", tags=["Products"])


@router.get(
    "",
    response_model=ProductListResponse,
    summary="List products",
    description="Returns all products scoped to the authenticated tenant.",
)
async def list_products(
    db: TenantSessionDep,
    skip: Annotated[int, Query(ge=0, description="Records to skip")] = 0,
    limit: Annotated[
        int, Query(ge=1, le=1000, description="Max records to return")
    ] = 100,
) -> ProductListResponse:
    # Count total
    count_q = select(func.count(Product.id))
    total_result = await db.execute(count_q)
    total = total_result.scalar_one()

    # Fetch page
    q = select(Product).offset(skip).limit(limit).order_by(Product.created_at.desc())
    result = await db.execute(q)
    products = result.scalars().all()

    return ProductListResponse(
        items=[ProductResponse.model_validate(p) for p in products],
        total=total,
    )
