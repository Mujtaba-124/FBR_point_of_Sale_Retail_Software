"""Authoritative server time for subscription decisions.

Subscription logic must call ``clock.utcnow()`` (never ``datetime.now()``
directly) so tests can move time across expiry boundaries without touching
the real system clock or real data. Always timezone-aware UTC.

End-to-end verification (``E2E_TEST_MODE``, disposable ``*_e2e`` database
only, refused in production) can drive the time of a whole QA stack, Celery
workers included, through the Redis key ``SIMULATED_CLOCK_KEY``. The
operating-system and Docker clocks are never changed.
"""

from datetime import UTC, datetime

SIMULATED_CLOCK_KEY = "e2e:clock:now"


def utcnow() -> datetime:
    simulated = _simulated_now()
    return simulated if simulated is not None else datetime.now(UTC)


def _simulated_now() -> datetime | None:
    from app.core.config import get_settings

    if not get_settings().e2e_test_mode:
        return None
    from app.core.redis import get_redis

    raw = get_redis().get(SIMULATED_CLOCK_KEY)
    if raw is None:
        return None
    value = datetime.fromisoformat(raw.decode() if isinstance(raw, bytes) else str(raw))
    if value.tzinfo is None:
        raise RuntimeError("The simulated clock must be timezone-aware")
    return value.astimezone(UTC)


def set_simulated_now(moment: datetime) -> None:
    """E2E driver only: freeze the QA stack's application time at ``moment``."""
    from app.core.config import get_settings
    from app.core.redis import get_redis

    if not get_settings().e2e_test_mode:
        raise RuntimeError("The simulated clock is only available in E2E_TEST_MODE")
    if moment.tzinfo is None:
        raise ValueError("moment must be timezone-aware")
    get_redis().set(SIMULATED_CLOCK_KEY, moment.astimezone(UTC).isoformat())
