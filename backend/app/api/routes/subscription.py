"""Super Admin subscription management. Every route requires a Super Admin."""

from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import DbSession, SuperAdmin
from app.models import AppSubscription
from app.models.app_subscription import SINGLETON_ID
from app.schemas.subscription_management import (
    RenewalOut,
    RenewalPageOut,
    RenewalRulesOut,
    RenewRequest,
    RenewResponse,
    SubscriptionManagementOut,
    subscription_out,
)
from app.schemas.super_admin import CompanyAccountOut
from app.services.subscription import business_today, summarize
from app.services.subscription_renewal import list_renewals, renew_subscription, renewal_window

router = APIRouter(prefix="/super-admin/subscription", tags=["super-admin"])


@router.get("", response_model=SubscriptionManagementOut)
def get_subscription(_: SuperAdmin, db: DbSession) -> SubscriptionManagementOut:
    today = business_today()
    record = db.get(AppSubscription, SINGLETON_ID)
    return SubscriptionManagementOut(
        today=today,
        company=CompanyAccountOut(name=record.company_name if record else None),
        subscription=subscription_out(summarize(record, today)),
        renewal=RenewalRulesOut.from_window(renewal_window(record, today)),
    )


@router.post(
    "/renew",
    response_model=RenewResponse,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "Replay of an already-completed renewal"}},
)
def renew(
    payload: RenewRequest, user: SuperAdmin, db: DbSession, response: Response
) -> RenewResponse:
    """Extend the expiry date. CSRF-protected (POST with a session cookie)."""
    outcome = renew_subscription(
        db,
        actor=user,
        new_expiry_date=payload.new_expiry_date,
        expected_expiry_date=payload.expected_expiry_date,
        idempotency_key=payload.idempotency_key,
        note=payload.renewal_note,
    )
    if not outcome.created:
        response.status_code = status.HTTP_200_OK
    today = business_today()
    return RenewResponse(
        renewal=RenewalOut.from_model(outcome.renewal),
        subscription=subscription_out(summarize(db.get(AppSubscription, SINGLETON_ID), today)),
        replayed=not outcome.created,
    )


@router.get("/renewals", response_model=RenewalPageOut)
def renewals(
    _: SuperAdmin,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RenewalPageOut:
    """Read-only history, newest first."""
    items, total = list_renewals(db, limit, offset)
    return RenewalPageOut(
        items=[RenewalOut.from_model(r) for r in items], total=total, limit=limit, offset=offset
    )
