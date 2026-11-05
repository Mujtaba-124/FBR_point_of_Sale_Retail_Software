"""Company Workspace subscription access policy (single source of truth).

Company access is allowed only while the subscription is valid, i.e. its
computed status is ACTIVE or EXPIRING_SOON. The status comes from the
database record and the server clock in Asia/Karachi calendar days, so a
subscription is valid through its whole final day and stops at 00:00
Pakistan time the day after the expiry date.

Fail-closed: a subscription that is expired, not started yet, not configured
or has invalid dates denies Company access. The Super Admin workspace never
calls this module, so it always stays reachable for renewal.

Used by:
- the HTTP guards for every Company Workspace route (``app.api.deps``),
- Company login (``app.services.auth_service``),
- future Company background jobs (``app.tasks.subscription_guard``).
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import AppSubscription
from app.models.app_subscription import SINGLETON_ID
from app.services.subscription import SubscriptionStatus, business_today, summarize

ALLOWED_STATUSES = frozenset({SubscriptionStatus.ACTIVE, SubscriptionStatus.EXPIRING_SOON})

# Stable machine-readable codes; the frontend switches on these, never on text.
_DENIALS: dict[SubscriptionStatus, tuple[str, str]] = {
    SubscriptionStatus.EXPIRED: (
        "subscription_expired",
        "Your software subscription has expired. Please contact your administrator for renewal.",
    ),
    SubscriptionStatus.SCHEDULED: (
        "subscription_not_started",
        "Your software subscription has not started yet. Please contact your administrator.",
    ),
    SubscriptionStatus.NOT_CONFIGURED: (
        "subscription_not_configured",
        "Your software subscription is not active. Please contact your administrator.",
    ),
    SubscriptionStatus.INVALID: (
        "subscription_not_configured",
        "Your software subscription is not active. Please contact your administrator.",
    ),
}

SUBSCRIPTION_ERROR_CODES = frozenset(code for code, _ in _DENIALS.values())


@dataclass(frozen=True)
class CompanyAccess:
    allowed: bool
    status: SubscriptionStatus
    code: str | None = None
    message: str | None = None


def company_access(db: Session) -> CompanyAccess:
    """Evaluate Company access right now. Reads the record on every call (no caching)."""
    record = db.get(AppSubscription, SINGLETON_ID)
    status = summarize(record, business_today()).status
    if status in ALLOWED_STATUSES:
        return CompanyAccess(True, status)
    code, message = _DENIALS[status]
    return CompanyAccess(False, status, code, message)


def subscription_denial(access: CompanyAccess) -> AppError:
    assert not access.allowed and access.code and access.message
    return AppError(403, access.code, access.message)


def ensure_company_access(db: Session) -> None:
    """Raise 403 with a subscription error code unless Company access is allowed."""
    access = company_access(db)
    if not access.allowed:
        raise subscription_denial(access)
