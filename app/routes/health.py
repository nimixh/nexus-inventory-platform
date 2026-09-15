import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.database import SessionDep
from app.redis import RedisDep

logger = logging.getLogger(__name__)

router = APIRouter()
settings = get_settings()


@router.get("/health")
async def health_check(db: SessionDep, redis: RedisDep) -> JSONResponse:
    db_status = "disconnected"
    redis_status = "disconnected"

    try:
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        logger.warning("Database health check failed", exc_info=True)

    try:
        await redis.ping()  # type: ignore[misc]
        redis_status = "connected"
    except Exception:
        logger.warning("Redis health check failed", exc_info=True)

    is_healthy = db_status == "connected" and redis_status == "connected"

    body = {
        "status": "ok" if is_healthy else "degraded",
        "db": db_status,
        "redis": redis_status,
        "version": settings.APP_VERSION,
    }
    return JSONResponse(
        content=body,
        status_code=200 if is_healthy else 503,
    )
