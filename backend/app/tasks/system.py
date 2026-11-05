from app.celery_app import celery_app


@celery_app.task(name="system.ping")
def ping() -> str:
    """Harmless task used to verify the worker and Redis connectivity."""
    return "pong"
