"""Subscription status rules (authoritative; the frontend only displays the result).

Calendar dates are evaluated in Pakistan time (Asia/Karachi):

- A subscription is valid from ``start_date`` through ``expiry_date`` inclusive.
- ``total_days``      = expiry - start + 1 (both ends count).
- ``days_remaining``  = expiry - today, never negative and never above total.
  It is 0 on the expiry day (still valid) and 0 after expiry (expired).
- ``days_used``       = today - start + 1, clamped to [0, total]. Today counts as
  used, so ``days_used + days_remaining == total_days`` on every valid day.
- Status:
  ``not_configured`` no record; ``invalid`` expiry before start (also blocked by
  a DB constraint); ``scheduled`` today is before start; ``expired`` today is
  after expiry; ``expiring_soon`` 15 or fewer days remain (including the expiry
  day); otherwise ``active``.
"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from app.core import clock
from app.models import AppSubscription

BUSINESS_TZ = ZoneInfo("Asia/Karachi")
EXPIRING_SOON_DAYS = 15


class SubscriptionStatus(StrEnum):
    NOT_CONFIGURED = "not_configured"
    INVALID = "invalid"
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    EXPIRING_SOON = "expiring_soon"
    EXPIRED = "expired"


@dataclass(frozen=True)
class SubscriptionSummary:
    status: SubscriptionStatus
    start_date: date | None = None
    expiry_date: date | None = None
    last_renewed_on: date | None = None
    total_days: int | None = None
    days_used: int | None = None
    days_remaining: int | None = None
    days_until_start: int | None = None
    progress_percent: float | None = None


def business_today(now: datetime | None = None) -> date:
    """Today's calendar date in Pakistan time, from the authoritative server clock."""
    return (now or clock.utcnow()).astimezone(BUSINESS_TZ).date()


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


def summarize(record: AppSubscription | None, today: date) -> SubscriptionSummary:
    if record is None:
        return SubscriptionSummary(SubscriptionStatus.NOT_CONFIGURED)

    start, expiry = record.start_date, record.expiry_date
    if expiry < start:
        return SubscriptionSummary(
            SubscriptionStatus.INVALID, start, expiry, record.last_renewed_on
        )

    total = (expiry - start).days + 1
    remaining = _clamp((expiry - today).days, 0, total)
    used = _clamp((today - start).days + 1, 0, total)

    if today > expiry:
        status = SubscriptionStatus.EXPIRED
    elif today < start:
        status = SubscriptionStatus.SCHEDULED
    elif remaining <= EXPIRING_SOON_DAYS:
        status = SubscriptionStatus.EXPIRING_SOON
    else:
        status = SubscriptionStatus.ACTIVE

    return SubscriptionSummary(
        status=status,
        start_date=start,
        expiry_date=expiry,
        last_renewed_on=record.last_renewed_on,
        total_days=total,
        days_used=used,
        days_remaining=remaining,
        days_until_start=(start - today).days if today < start else 0,
        progress_percent=round(used / total * 100, 1),
    )
