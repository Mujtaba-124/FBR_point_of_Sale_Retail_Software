"""Super Admin subscription reminder settings and read-only activity.

Super Admin only (Company accounts: 403); the PUT is CSRF-protected by
``current_session``. There is deliberately no endpoint that triggers or
re-sends reminders: they are sent only by the Celery scheduler.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DbSession, SuperAdmin
from app.schemas.reminders import (
    OutboxStatus,
    ReminderHistoryItemOut,
    ReminderHistoryOut,
    ReminderOverviewOut,
    UpdateReminderSettingsRequest,
)
from app.services import reminder_settings as svc

router = APIRouter(prefix="/super-admin/email-settings", tags=["super-admin"])


@router.get("/reminders", response_model=ReminderOverviewOut)
def read_reminders(_: SuperAdmin, db: DbSession) -> ReminderOverviewOut:
    return ReminderOverviewOut.build(svc.overview(db))


@router.put("/reminders", response_model=ReminderOverviewOut)
def update_reminders(
    payload: UpdateReminderSettingsRequest, user: SuperAdmin, db: DbSession
) -> ReminderOverviewOut:
    svc.update_settings(
        db,
        actor=user,
        is_enabled=payload.is_enabled,
        notify_super_admin=payload.notify_super_admin,
        notify_company_admin=payload.notify_company_admin,
        expected_version=payload.expected_version,
    )
    return ReminderOverviewOut.build(svc.overview(db))


@router.get("/reminder-history", response_model=ReminderHistoryOut)
def reminder_history(
    _: SuperAdmin,
    db: DbSession,
    status: Annotated[OutboxStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> ReminderHistoryOut:
    rows, total, counts = svc.history(db, status=status, limit=limit, offset=offset)
    return ReminderHistoryOut(
        items=[ReminderHistoryItemOut.from_model(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
        counts=counts,
    )
