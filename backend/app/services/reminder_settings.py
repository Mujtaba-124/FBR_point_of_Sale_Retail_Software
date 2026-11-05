"""Super Admin reminder settings and read-only reminder activity."""

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import mask_email
from app.models import AppSubscription, AuditEvent, EmailOutbox, SubscriptionReminderSettings, User
from app.models import reminders as m
from app.models.app_subscription import SINGLETON_ID as SUBSCRIPTION_ID
from app.services import email_settings as email_svc
from app.services.reminder_outbox import (
    SEND_HOUR_PKT,
    cancel_open,
    get_reminder_settings,
)
from app.services.reminder_schedule import (
    RecipientResolution,
    ReminderStage,
    due_stage,
    resolve_recipients,
    schedule_window,
)
from app.services.subscription import business_today

logger = logging.getLogger(__name__)

HISTORY_STATUSES = m.OUTBOX_STATUSES


def _stale() -> AppError:
    return AppError(
        409,
        "stale_reminder_settings",
        "The reminder settings were changed after this page was opened. Reload and try again.",
    )


@dataclass(frozen=True)
class ReminderOverview:
    settings: SubscriptionReminderSettings
    today: date
    expiry_date: date | None
    today_stage: ReminderStage | None
    next_reminder_date: date | None
    window: tuple[date, date] | None
    email_configured: bool
    email_enabled: bool
    resolution: RecipientResolution
    company_admin_emails: list[str]
    super_admin_email: str | None


def next_reminder_date(
    record: AppSubscription | None, today: date, *, today_done: bool = False
) -> date | None:
    """The next calendar day a reminder will be queued for. ``today_done`` means
    today's reminders for the current expiry date already exist."""
    if record is None or record.expiry_date < record.start_date:
        return None
    first, last = schedule_window(record.expiry_date)
    earliest = today + timedelta(days=1) if today_done else today
    candidate = max(first, earliest, record.start_date)
    return candidate if candidate <= last else None


def _today_done(db: Session, record: AppSubscription | None, today: date) -> bool:
    if record is None:
        return False
    return bool(
        db.scalar(
            select(func.count())
            .select_from(EmailOutbox)
            .where(
                EmailOutbox.kind == m.KIND_SUBSCRIPTION_REMINDER,
                EmailOutbox.expiry_date == record.expiry_date,
                EmailOutbox.scheduled_date == today,
            )
        )
    )


def overview(db: Session) -> ReminderOverview:
    settings = get_reminder_settings(db)
    today = business_today()
    subscription = db.get(AppSubscription, SUBSCRIPTION_ID)
    email_row = email_svc.get_email_settings(db)
    # Preview with both categories so the admin sees who each switch covers.
    preview = resolve_recipients(db, notify_super_admin=True, notify_company_admin=True)
    supers = [r.email for r in preview.recipients if "super_admin" in r.categories]
    companies = [r.email for r in preview.recipients if "company_admin" in r.categories]
    return ReminderOverview(
        settings=settings,
        today=today,
        expiry_date=subscription.expiry_date if subscription else None,
        today_stage=due_stage(subscription, today),
        next_reminder_date=next_reminder_date(
            subscription, today, today_done=_today_done(db, subscription, today)
        ),
        window=schedule_window(subscription.expiry_date) if subscription else None,
        email_configured=email_row is not None,
        email_enabled=bool(email_row and email_row.is_enabled),
        resolution=preview,
        company_admin_emails=[mask_email(e) for e in companies],
        super_admin_email=mask_email(supers[0]) if supers else None,
    )


def update_settings(
    db: Session,
    *,
    actor: User,
    is_enabled: bool,
    notify_super_admin: bool,
    notify_company_admin: bool,
    expected_version: int,
) -> SubscriptionReminderSettings:
    try:
        row = get_reminder_settings(db, lock=True)
        if row.version != expected_version:
            raise _stale()
        if is_enabled and not (notify_super_admin or notify_company_admin):
            raise AppError(
                422,
                "invalid_reminder_settings",
                "Choose at least one recipient group before enabling reminders.",
            )
        before = {
            "is_enabled": row.is_enabled,
            "notify_super_admin": row.notify_super_admin,
            "notify_company_admin": row.notify_company_admin,
        }
        after = {
            "is_enabled": is_enabled,
            "notify_super_admin": notify_super_admin,
            "notify_company_admin": notify_company_admin,
        }
        if before == after:
            db.rollback()
            return row
        row.is_enabled = is_enabled
        row.notify_super_admin = notify_super_admin
        row.notify_company_admin = notify_company_admin
        row.version += 1
        row.updated_by_user_id = actor.id
        actor_ref = f"user:{actor.id}"
        if before["is_enabled"] != is_enabled:
            db.add(
                AuditEvent(
                    action="reminder.enabled" if is_enabled else "reminder.disabled",
                    actor=actor_ref,
                    details={"version": row.version},
                )
            )
        recipient_changes = {
            k: after[k]
            for k in ("notify_super_admin", "notify_company_admin")
            if before[k] != after[k]
        }
        if recipient_changes:
            db.add(
                AuditEvent(
                    action="reminder.recipients_updated",
                    actor=actor_ref,
                    details={**recipient_changes, "version": row.version},
                )
            )
        if before["is_enabled"] and not is_enabled:
            cancel_open(db, reason="reminders_disabled", actor=actor_ref)
        db.commit()
    except Exception:
        db.rollback()
        raise
    logger.info("reminder settings updated by %s: %s", actor.id, after)
    return row


def history(
    db: Session, *, status: str | None, limit: int, offset: int
) -> tuple[list[EmailOutbox], int, dict[str, int]]:
    base = select(EmailOutbox).where(EmailOutbox.kind == m.KIND_SUBSCRIPTION_REMINDER)
    if status:
        base = base.where(EmailOutbox.status == status)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(
            EmailOutbox.scheduled_date.desc(),
            EmailOutbox.created_at.desc(),
            EmailOutbox.recipient_email,
        )
        .limit(limit)
        .offset(offset)
    ).all()
    counts: dict[str, int] = {
        str(status): int(count)
        for status, count in db.execute(
            select(EmailOutbox.status, func.count())
            .where(EmailOutbox.kind == m.KIND_SUBSCRIPTION_REMINDER)
            .group_by(EmailOutbox.status)
        ).all()
    }
    return list(rows), int(total), {s: int(counts.get(s, 0)) for s in HISTORY_STATUSES}


def send_hour_label() -> str:
    return f"{SEND_HOUR_PKT:02d}:00"
