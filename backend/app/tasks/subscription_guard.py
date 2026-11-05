"""Subscription enforcement for Company background work (Celery).

HTTP requests are guarded in ``app.api.deps``. Background jobs have no request,
so Company business tasks must use this module instead. It reuses the same
policy (``app.services.subscription_access``): valid only while the
subscription is ACTIVE or EXPIRING_SOON, evaluated in Asia/Karachi calendar
days from the database and server clock.

Rules for future Company tasks (Excel processing, approvals, FBR sync, reports):

1. Decorate the task body with ``@requires_company_subscription``. It checks the
   subscription when the worker STARTS the task, not just when it was queued, so
   a job queued before expiry but picked up after expiry does nothing.
2. Long-running jobs must also call ``ensure_company_subscription(db)`` at every
   safe boundary before an external side effect, for example before each FBR
   invoice submission or each Excel batch commit. Expiry in the middle of a job
   then stops further work cleanly. Commit or record progress first, so a
   resumed job after renewal continues where it stopped.
3. A blocked task returns ``{"status": "skipped", "reason": <code>}`` and does
   not retry automatically. Re-queue it after renewal if needed.

System tasks (health checks such as ``system.ping``, cleanup, audit, and
subscription administration) must NOT use this guard.
"""

import functools
import logging
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

from sqlalchemy.orm import Session, sessionmaker

from app.db.session import get_engine
from app.services.subscription_access import company_access

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


class CompanySubscriptionInactive(Exception):
    """Company business processing is not allowed by the current subscription."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def ensure_company_subscription(db: Session) -> None:
    """Raise ``CompanySubscriptionInactive`` unless Company processing is allowed now."""
    access = company_access(db)
    if not access.allowed:
        assert access.code is not None
        raise CompanySubscriptionInactive(access.code)


def requires_company_subscription(func: Callable[P, R]) -> Callable[P, R | dict[str, Any]]:
    """Skip the task (no side effects) when the subscription is not valid at start time.

    Checkpoints inside the task (``ensure_company_subscription``) raise the same
    exception, which is also turned into a clean "skipped" result here.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | dict[str, Any]:
        db = sessionmaker(bind=get_engine(), autoflush=False)()
        try:
            ensure_company_subscription(db)
        except CompanySubscriptionInactive as exc:
            logger.warning("company task %s skipped: %s", func.__name__, exc.code)
            return {"status": "skipped", "reason": exc.code}
        finally:
            db.close()
        try:
            return func(*args, **kwargs)
        except CompanySubscriptionInactive as exc:
            logger.warning("company task %s stopped at checkpoint: %s", func.__name__, exc.code)
            return {"status": "skipped", "reason": exc.code}

    return wrapper
