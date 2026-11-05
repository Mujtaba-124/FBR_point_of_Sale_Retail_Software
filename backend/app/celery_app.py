from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "cheena",
    broker=_settings.celery_broker_url or _settings.redis_url,
    backend=_settings.celery_result_backend or _settings.redis_url,
    include=["app.tasks.system", "app.tasks.reminders"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # Beat only sends wake-up signals; the work and its state live in PostgreSQL,
    # so a lost or duplicated signal is harmless.
    beat_schedule={
        # Evaluated in Asia/Karachi days inside the task; every 30 minutes so a
        # missed run is made up the same day.
        "reminders-evaluate": {
            "task": "reminders.evaluate",
            "schedule": crontab(minute="5,35"),
            "options": {"expires": 25 * 60},
        },
        # Retries, recovery after crashes, and anything queued meanwhile.
        "email-outbox-dispatch": {
            "task": "email_outbox.dispatch",
            "schedule": 60.0,
            "options": {"expires": 55},
        },
    },
)
