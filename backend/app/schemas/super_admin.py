from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.services.subscription import EXPIRING_SOON_DAYS, SubscriptionStatus
from app.services.super_admin_dashboard import ContactStatus, DashboardData


class CompanyAccountOut(BaseModel):
    name: str | None
    account_type: Literal["single_company"] = "single_company"


class CompanyAdminContactOut(BaseModel):
    """Limited, read-only contact details. Never a user list."""

    status: ContactStatus
    count: int
    full_name: str | None
    email: str | None
    is_active: bool | None


class SubscriptionOut(BaseModel):
    status: SubscriptionStatus
    start_date: date | None
    expiry_date: date | None
    last_renewed_on: date | None
    total_days: int | None
    days_used: int | None
    days_remaining: int | None
    days_until_start: int | None
    progress_percent: float | None
    expiring_soon_threshold_days: int = EXPIRING_SOON_DAYS


class SuperAdminDashboardOut(BaseModel):
    today: date
    timezone: Literal["Asia/Karachi"] = "Asia/Karachi"
    company: CompanyAccountOut
    company_admin: CompanyAdminContactOut
    subscription: SubscriptionOut

    @classmethod
    def from_data(cls, data: DashboardData) -> "SuperAdminDashboardOut":
        s, c = data.subscription, data.company_admin
        return cls(
            today=data.today,
            company=CompanyAccountOut(name=data.company_name),
            company_admin=CompanyAdminContactOut(
                status=c.status,
                count=c.count,
                full_name=c.full_name,
                email=c.email,
                is_active=c.is_active,
            ),
            subscription=SubscriptionOut(
                status=s.status,
                start_date=s.start_date,
                expiry_date=s.expiry_date,
                last_renewed_on=s.last_renewed_on,
                total_days=s.total_days,
                days_used=s.days_used,
                days_remaining=s.days_remaining,
                days_until_start=s.days_until_start,
                progress_percent=s.progress_percent,
            ),
        )
