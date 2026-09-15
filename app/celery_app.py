from celery import Celery

from app.config import get_settings

settings = get_settings()

broker_url = settings.CELERY_BROKER_URL or settings.REDIS_URL
result_backend = settings.CELERY_RESULT_BACKEND or settings.REDIS_URL

celery_app = Celery(
    "nexus-inventory",
    broker=broker_url,
    backend=result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "sync_erp_data": {"queue": "sync"},
    },
    task_default_queue="default",
    broker_connection_retry_on_startup=True,
)

# Register tasks explicitly — autodiscover can miss submodules in some environments.
import app.tasks.sync  # noqa: F401, E402

celery_app.autodiscover_tasks(["app.tasks"])
