"""Read-only data for the Super Admin dashboard.

Exposes only the single company's subscription and a limited Company Admin
contact (name, email, active flag). No company users list, sessions,
credentials or business data are ever read here.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AccessCategory, AppSubscription, User
from app.models.app_subscription import SINGLETON_ID
from app.services.subscription import SubscriptionSummary, business_today, summarize


class ContactStatus(StrEnum):
    AVAILABLE = "available"
    NOT_FOUND = "not_found"
    # More than one Company Admin and no designated primary contact: show
    # nobody rather than pick one arbitrarily.
    MULTIPLE = "multiple"


@dataclass(frozen=True)
class AdminContact:
    status: ContactStatus
    count: int
    full_name: str | None = None
    email: str | None = None
    is_active: bool | None = None


@dataclass(frozen=True)
class DashboardData:
    today: date
    company_name: str | None
    subscription: SubscriptionSummary
    company_admin: AdminContact


def _company_admin_contact(db: Session) -> AdminContact:
    # Fetch at most two rows: enough to tell "one" from "several".
    rows = db.execute(
        select(User.full_name, User.email, User.is_active)
        .where(User.access_category == AccessCategory.COMPANY_ADMIN)
        .order_by(User.created_at)
        .limit(2)
    ).all()
    if not rows:
        return AdminContact(ContactStatus.NOT_FOUND, 0)
    if len(rows) > 1:
        count = db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.access_category == AccessCategory.COMPANY_ADMIN)
        )
        return AdminContact(ContactStatus.MULTIPLE, int(count or 0))
    name, email, active = rows[0]
    return AdminContact(ContactStatus.AVAILABLE, 1, name, email, active)


def get_dashboard(db: Session, today: date | None = None) -> DashboardData:
    record = db.get(AppSubscription, SINGLETON_ID)
    today = today or business_today()
    return DashboardData(
        today=today,
        company_name=record.company_name if record else None,
        subscription=summarize(record, today),
        company_admin=_company_admin_contact(db),
    )
