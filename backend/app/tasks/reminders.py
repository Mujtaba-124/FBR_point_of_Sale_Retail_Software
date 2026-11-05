"""Celery tasks for subscription expiry reminders.

These are System tasks (subscription administration), so they deliberately do
NOT use ``requires_company_subscription``: reminders must keep working after
expiry. All state lives in PostgreSQL (``app.services.reminder_outbox``); the
tasks are safe to run repeatedly, concurrently and after restarts.
"""

import logging
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.celery_app import celery_app
from app.db.session import get_engine
from app.services import reminder_outbox
from app.services.smtp_transport import get_smtp_transport

logger = logging.getLogger(__name__)


def _session() -> Session:
    return sessionmaker(bind=get_engine(), autoflush=False)()


@celery_app.task(name="reminders.evaluate", ignore_result=True)
def evaluate_reminders() -> dict[str, Any]:
    """Beat: queue today's reminders (idempotent), then wake the dispatcher."""
    with _session() as db:
        result = reminder_outbox.evaluate(db)
    if result.queued:
        dispatch_email_outbox.delay()
    return {"result": result.result, "queued": result.queued}


@celery_app.task(name="email_outbox.dispatch", ignore_result=True)
def dispatch_email_outbox() -> dict[str, Any]:
    """Beat + on demand: recover interrupted deliveries and send due rows."""
    result = reminder_outbox.dispatch_due(_session, get_smtp_transport())
    return {"recovered": result.recovered, "handled": result.handled, **result.statuses}
