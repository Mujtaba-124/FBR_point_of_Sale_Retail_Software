"""Company Admin dashboard summary (Phase 1).

Only facts the database can actually answer are reported as numbers. Modules
that do not exist yet (Excel uploads, approvals, FBR sync, sales) are
reported as ``unavailable`` with no value: never as zero, never estimated.
When a module is built, its metric switches to a real query here.
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AccessCategory, AppSubscription, User
from app.models.app_subscription import SINGLETON_ID
from app.services.shop_allowance import AllowanceUsage, get_usage

# Reason codes for metrics whose module is not implemented yet.
APPROVALS_NOT_AVAILABLE = "approval_workflow_not_available"
FBR_SYNC_NOT_AVAILABLE = "fbr_sync_not_available"
UPLOADS_NOT_AVAILABLE = "excel_upload_not_available"

COMPANY_CATEGORIES = (AccessCategory.COMPANY_ADMIN, AccessCategory.COMPANY_USER)


@dataclass(frozen=True)
class Metric:
    value: int | None
    unavailable_reason: str | None = None

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None


@dataclass(frozen=True)
class CompanyDashboard:
    company_name: str | None
    total_shops: Metric
    active_shops: Metric
    active_users: Metric
    pending_approvals: Metric
    pending_fbr_sync: Metric
    uploads_reason: str
    shop_allowance: AllowanceUsage


def count_active_company_users(db: Session) -> int:
    """Active Company Admin and Company User accounts. Super Admins are excluded."""
    return int(
        db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.access_category.in_(COMPANY_CATEGORIES), User.is_active.is_(True))
        )
        or 0
    )


def get_company_dashboard(db: Session) -> CompanyDashboard:
    from app.services.shops import counts as shop_counts

    subscription = db.get(AppSubscription, SINGLETON_ID)
    shops = shop_counts(db)
    return CompanyDashboard(
        company_name=subscription.company_name if subscription else None,
        total_shops=Metric(shops.total),  # active and inactive shops
        active_shops=Metric(shops.active),
        active_users=Metric(count_active_company_users(db)),
        pending_approvals=Metric(None, APPROVALS_NOT_AVAILABLE),
        pending_fbr_sync=Metric(None, FBR_SYNC_NOT_AVAILABLE),
        uploads_reason=UPLOADS_NOT_AVAILABLE,
        shop_allowance=get_usage(db),
    )
