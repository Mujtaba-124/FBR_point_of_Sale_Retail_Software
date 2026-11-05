"""Authoritative server time for subscription decisions.

Subscription logic must call ``clock.utcnow()`` (never ``datetime.now()``
directly) so tests can move time across expiry boundaries without touching
the real system clock or real data. Always timezone-aware UTC.
"""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)
