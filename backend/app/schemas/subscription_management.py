import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import SubscriptionRenewal
from app.schemas.super_admin import CompanyAccountOut, SubscriptionOut
from app.services.subscription import SubscriptionSummary
from app.services.subscription_renewal import NOTE_MAX_LENGTH, RenewalWindow


def subscription_out(s: SubscriptionSummary) -> SubscriptionOut:
    return SubscriptionOut(
        status=s.status,
        start_date=s.start_date,
        expiry_date=s.expiry_date,
        last_renewed_on=s.last_renewed_on,
        total_days=s.total_days,
        days_used=s.days_used,
        days_remaining=s.days_remaining,
        days_until_start=s.days_until_start,
        progress_percent=s.progress_percent,
    )


class RenewalRulesOut(BaseModel):
    can_renew: bool
    min_new_expiry_date: date | None
    max_new_expiry_date: date | None

    @classmethod
    def from_window(cls, w: RenewalWindow) -> "RenewalRulesOut":
        return cls(
            can_renew=w.can_renew,
            min_new_expiry_date=w.min_new_expiry_date,
            max_new_expiry_date=w.max_new_expiry_date,
        )


class SubscriptionManagementOut(BaseModel):
    today: date
    timezone: Literal["Asia/Karachi"] = "Asia/Karachi"
    company: CompanyAccountOut
    subscription: SubscriptionOut
    renewal: RenewalRulesOut


class RenewedByOut(BaseModel):
    full_name: str
    email: str


class RenewalOut(BaseModel):
    id: uuid.UUID
    renewed_at: datetime
    previous_expiry_date: date
    new_expiry_date: date
    renewal_note: str | None
    renewed_by: RenewedByOut

    @classmethod
    def from_model(cls, r: SubscriptionRenewal) -> "RenewalOut":
        return cls(
            id=r.id,
            renewed_at=r.renewed_at,
            previous_expiry_date=r.previous_expiry_date,
            new_expiry_date=r.new_expiry_date,
            renewal_note=r.renewal_note,
            renewed_by=RenewedByOut(full_name=r.renewed_by.full_name, email=r.renewed_by.email),
        )


class RenewalPageOut(BaseModel):
    items: list[RenewalOut]
    total: int
    limit: int
    offset: int


class RenewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_expiry_date: date
    # The expiry date the form was opened with (optimistic concurrency check).
    expected_expiry_date: date
    idempotency_key: uuid.UUID
    renewal_note: str | None = Field(default=None, max_length=NOTE_MAX_LENGTH * 2)


class RenewResponse(BaseModel):
    renewal: RenewalOut
    subscription: SubscriptionOut
    replayed: bool
