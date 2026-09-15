from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis

from app.config import get_settings

settings = get_settings()

redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)


async def get_redis() -> Redis:
    return redis_client


RedisDep = Annotated[Redis, Depends(get_redis)]
