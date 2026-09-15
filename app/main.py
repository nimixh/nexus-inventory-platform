from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.database import admin_engine, engine
from app.redis import redis_client
from app.routes.auth import router as auth_router
from app.routes.health import router as health_router
from app.routes.integrations import router as integrations_router
from app.routes.products import router as products_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await redis_client.aclose()
    await engine.dispose()
    await admin_engine.dispose()


settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(integrations_router, prefix="/api/v1")
app.include_router(products_router, prefix="/api/v1")
