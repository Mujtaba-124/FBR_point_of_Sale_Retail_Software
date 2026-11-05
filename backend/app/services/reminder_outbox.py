"""Durable reminder outbox: scheduling, claiming, delivery, retries and recovery.

Flow (all state lives in PostgreSQL; Celery tasks only trigger these functions):

1. ``evaluate`` (Beat, every 30 min): if reminders are enabled and today
   (Asia/Karachi) is a reminder day at or after SEND_HOUR_PKT, insert one
   ``email_outbox`` row per recipient with INSERT ... ON CONFLICT DO NOTHING on
   the reminder identity (subscription, expiry date, stage, date, recipient).
   Running it any number of times, in parallel, creates each reminder once.
2. ``dispatch_due`` (Beat, every minute, and right after queueing):
   - ``recover_expired_leases``: rows stuck in ``processing`` past their lease
     (worker crashed) get their attempt marked ``uncertain`` and are retried.
   - ``claim_next``: ``SELECT ... FOR UPDATE SKIP LOCKED`` picks one due row, so
     parallel workers never take the same row. Every eligibility rule is
     re-checked right there (settings, global sending, SMTP configuration,
     current expiry date, send date, recipient eligibility); ineligible rows
     are cancelled and kept as history. Eligible rows move to ``processing``
     with a lease, and the attempt is recorded, before any SMTP traffic.
   - ``deliver``: one SMTP send through the existing secure transport, then
     the outcome is recorded: ``accepted`` (accepted by the SMTP server, which
     is not proof of inbox delivery), ``retry_scheduled`` (transient error,
     exponential backoff), or ``failed_permanent`` (permanent rejection or
     retries exhausted).

Catch-up policy (bounded): a reminder is only ever sent on its own scheduled
date. Missed days are never back-filled; after an outage the next evaluation
queues only TODAY's reminder, and open rows from earlier dates are cancelled
(``missed_send_window``). Evaluation runs every 30 minutes, so a missed run is
made up within the same day.

Delivery semantics: at-least-once with duplicate suppression, not exactly-once.
If a worker dies after the SMTP server accepted a message but before the
result was stored, the row's lease expires, the attempt is recorded as
``uncertain`` and the reminder is retried, which may deliver a duplicate. Every
message carries a stable Message-ID per outbox row so mail systems can
recognise the repeat. A database uniqueness constraint (not Redis) prevents
duplicate scheduling.
"""

import logging
import socket
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import format_datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import AppError
from app.core.security import mask_email
from app.models import (
    AppSubscription,
    AuditEvent,
    EmailDeliveryAttempt,
    EmailOutbox,
    SubscriptionReminderSettings,
)
from app.models import reminders as m
from app.models.app_subscription import SINGLETON_ID as SUBSCRIPTION_ID
from app.services import email_settings as email_svc
from app.services.reminder_schedule import ReminderStage, due_stage, resolve_recipients
from app.services.reminder_templates import render_reminder
from app.services.smtp_transport import SmtpConfig, SmtpFailure, SmtpTransport
from app.services.subscription import BUSINESS_TZ, business_today, summarize

logger = logging.getLogger(__name__)

SEND_HOUR_PKT = 9  # reminders are queued from 09:00 Pakistan time
MAX_ATTEMPTS = 5
# Delay before attempt 2, 3, 4, 5 (exponential, bounded to the same day).
BACKOFF_SECONDS = (60, 5 * 60, 15 * 60, 45 * 60)
LEASE_SECONDS = 5 * 60  # longer than any bounded SMTP exchange
DISPATCH_BATCH = 50

SCHEDULER_ACTOR = "system:reminder_scheduler"
WORKER_ACTOR = "system:reminder_worker"

STATUS_LABELS = {
    "active": "Active",
    "expiring_soon": "Expiring Soon",
    "expired": "Expired",
    "scheduled": "Not Started",
    "not_configured": "Not Configured",
    "invalid": "Invalid Dates",
}


def worker_id() -> str:
    return f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"


def _audit(db: Session, actor: str, action: str, details: dict[str, Any]) -> None:
    db.add(AuditEvent(action=action, actor=actor, details=details))


def get_reminder_settings(db: Session, *, lock: bool = False) -> SubscriptionReminderSettings:
    stmt = select(SubscriptionReminderSettings).where(
        SubscriptionReminderSettings.id == m.SINGLETON_ID
    )
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if row is None:  # the migration inserts it; recreate defensively (disabled)
        row = SubscriptionReminderSettings(id=m.SINGLETON_ID, is_enabled=False, version=1)
        db.add(row)
        db.flush()
    return row


# --- Cancellation ------------------------------------------------------------


def cancel_obsolete(db: Session, *, current_expiry: date, actor: str) -> int:
    """Cancel open reminders scheduled for any other expiry date (call inside the
    renewal transaction). History rows are kept; nothing is deleted."""
    now = clock.utcnow()
    result = db.execute(
        update(EmailOutbox)
        .where(
            EmailOutbox.kind == m.KIND_SUBSCRIPTION_REMINDER,
            EmailOutbox.status.in_(m.OPEN_STATUSES),
            EmailOutbox.expiry_date != current_expiry,
        )
        .values(
            status=m.CANCELLED_OBSOLETE,
            cancel_reason="subscription_renewed",
            cancelled_at=now,
            lease_expires_at=None,
        )
        .execution_options(synchronize_session=False)
    )
    count = int(result.rowcount or 0)  # type: ignore[attr-defined]
    if count:
        _audit(
            db,
            actor,
            "reminder.jobs_cancelled_obsolete",
            {"count": count, "current_expiry_date": current_expiry.isoformat()},
        )
    return count


def cancel_open(db: Session, *, reason: str, actor: str) -> int:
    now = clock.utcnow()
    result = db.execute(
        update(EmailOutbox)
        .where(
            EmailOutbox.kind == m.KIND_SUBSCRIPTION_REMINDER,
            EmailOutbox.status.in_(m.OPEN_STATUSES),
        )
        .values(status=m.CANCELLED, cancel_reason=reason, cancelled_at=now)
        .execution_options(synchronize_session=False)
    )
    count = int(result.rowcount or 0)  # type: ignore[attr-defined]
    if count:
        _audit(db, actor, "reminder.jobs_cancelled", {"count": count, "reason": reason})
    return count


def _cancel_missed(db: Session, today: date) -> int:
    now = clock.utcnow()
    result = db.execute(
        update(EmailOutbox)
        .where(
            EmailOutbox.kind == m.KIND_SUBSCRIPTION_REMINDER,
            EmailOutbox.status.in_(m.OPEN_STATUSES),
            EmailOutbox.scheduled_date < today,
        )
        .values(status=m.CANCELLED, cancel_reason="missed_send_window", cancelled_at=now)
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


# --- Evaluation (scheduler) --------------------------------------------------


@dataclass
class EvaluationResult:
    result: str
    business_date: date
    stage: ReminderStage | None = None
    queued: int = 0
    already_queued: int = 0
    cancelled_obsolete: int = 0
    cancelled_missed: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "business_date": self.business_date.isoformat(),
            "days_offset": self.stage.days_offset if self.stage else None,
            "queued": self.queued,
            "already_queued": self.already_queued,
            "cancelled_obsolete": self.cancelled_obsolete,
            "cancelled_missed": self.cancelled_missed,
            **self.details,
        }


def evaluate(db: Session, *, now: datetime | None = None) -> EvaluationResult:
    """Queue today's reminders (idempotent). Commits."""
    now = now or clock.utcnow()
    today = business_today(now)
    local_hour = now.astimezone(BUSINESS_TZ).hour
    try:
        # Row lock serializes concurrent evaluations (the unique constraint
        # would still prevent duplicates without it).
        settings = get_reminder_settings(db, lock=True)
        subscription = db.get(AppSubscription, SUBSCRIPTION_ID)
        out = EvaluationResult(result="", business_date=today)

        if subscription is not None:
            out.cancelled_obsolete = cancel_obsolete(
                db, current_expiry=subscription.expiry_date, actor=SCHEDULER_ACTOR
            )
        out.cancelled_missed = _cancel_missed(db, today)

        email_row = email_svc.get_email_settings(db)
        stage = due_stage(subscription, today)
        out.stage = stage
        if not settings.is_enabled:
            out.result = "reminders_disabled"
        elif subscription is None or subscription.expiry_date < subscription.start_date:
            out.result = "subscription_not_configured"
        elif email_row is None:
            out.result = "email_not_configured"
        elif not email_row.is_enabled:
            out.result = "email_sending_disabled"
        elif stage is None:
            out.result = "no_reminder_due"
        elif local_hour < SEND_HOUR_PKT:
            out.result = "waiting_for_send_time"
        else:
            resolution = resolve_recipients(
                db,
                notify_super_admin=settings.notify_super_admin,
                notify_company_admin=settings.notify_company_admin,
            )
            out.details = {
                "super_admin": resolution.super_admin_status,
                "company_admins": resolution.company_admin_count,
                "company_admins_without_valid_email": resolution.skipped_company_admins,
                "recipients": len(resolution.recipients),
            }
            if not resolution.recipients:
                out.result = "no_recipients"
            else:
                for recipient in resolution.recipients:
                    inserted = db.execute(
                        insert(EmailOutbox)
                        .values(
                            id=uuid.uuid4(),
                            kind=m.KIND_SUBSCRIPTION_REMINDER,
                            subscription_id=subscription.id,
                            expiry_date=subscription.expiry_date,
                            days_offset=stage.days_offset,
                            scheduled_date=today,
                            recipient_email=recipient.email,
                            recipient_categories=recipient.categories,
                            status=m.PENDING,
                            attempt_count=0,
                            max_attempts=MAX_ATTEMPTS,
                            next_attempt_at=now,
                        )
                        .on_conflict_do_nothing(constraint="uq_email_outbox_reminder_identity")
                        .returning(EmailOutbox.id)
                    ).scalar_one_or_none()
                    if inserted is None:
                        out.already_queued += 1
                    else:
                        out.queued += 1
                out.result = "queued" if out.queued else "already_queued"

        if out.queued:
            _audit(
                db,
                SCHEDULER_ACTOR,
                "reminder.jobs_queued",
                {
                    "count": out.queued,
                    "days_offset": stage.days_offset if stage else None,
                    "scheduled_date": today.isoformat(),
                    "expiry_date": subscription.expiry_date.isoformat() if subscription else None,
                },
            )
        # Audit an evaluation only when its outcome changes, not on every poll.
        if out.result != settings.last_run_result or out.queued or out.cancelled_missed:
            _audit(
                db,
                SCHEDULER_ACTOR,
                "reminder.schedule_evaluated",
                {"result": out.result, **out.summary()},
            )
        settings.last_run_at = now
        settings.last_run_business_date = today
        settings.last_run_result = out.result
        settings.last_run_details = out.summary()
        db.commit()
    except Exception:
        db.rollback()
        raise
    logger.info("reminder evaluation: %s (queued=%s)", out.result, out.queued)
    return out


# --- Claiming and delivery (workers) -----------------------------------------


@dataclass(frozen=True)
class Claim:
    outbox_id: uuid.UUID
    attempt_number: int
    worker: str
    config: SmtpConfig
    message: EmailMessage


def _ineligibility(
    db: Session, row: EmailOutbox, settings: SubscriptionReminderSettings, today: date
) -> tuple[str, str] | None:
    """(status, reason) when the row must not be sent now, else None."""
    if not settings.is_enabled:
        return m.CANCELLED, "reminders_disabled"
    subscription = db.get(AppSubscription, row.subscription_id)
    if subscription is None:
        return m.CANCELLED, "subscription_not_configured"
    if subscription.expiry_date != row.expiry_date:
        return m.CANCELLED_OBSOLETE, "subscription_renewed"
    if row.scheduled_date != today:
        return m.CANCELLED, "missed_send_window"
    stage = due_stage(subscription, today)
    if stage is None or stage.days_offset != row.days_offset:
        return m.CANCELLED_OBSOLETE, "schedule_changed"
    email_row = email_svc.get_email_settings(db)
    if email_row is None:
        return m.CANCELLED, "email_not_configured"
    if not email_row.is_enabled:
        return m.CANCELLED, "email_sending_disabled"
    current = resolve_recipients(
        db,
        notify_super_admin=settings.notify_super_admin,
        notify_company_admin=settings.notify_company_admin,
    )
    if row.recipient_email not in {r.email for r in current.recipients}:
        return m.CANCELLED, "recipient_not_eligible"
    return None


def build_message(
    db: Session, row: EmailOutbox, subscription: AppSubscription, today: date
) -> EmailMessage:
    email_row = email_svc.get_email_settings(db)
    assert email_row is not None
    content = render_reminder(
        stage=ReminderStage(row.days_offset),
        company_name=subscription.company_name,
        expiry_date=row.expiry_date,
        status_label=STATUS_LABELS.get(summarize(subscription, today).status, "Unknown"),
    )
    sender = Address(display_name=email_row.sender_name, addr_spec=email_row.sender_email)
    message = EmailMessage()
    message["Subject"] = content.subject
    message["From"] = sender
    message["To"] = Address(addr_spec=row.recipient_email)
    message["Date"] = format_datetime(clock.utcnow())
    # Stable per outbox row, so a retried (possibly duplicate) send is recognisable.
    message["Message-ID"] = f"<reminder.{row.id}@{sender.domain or 'cheena-pos.local'}>"
    message["Auto-Submitted"] = "auto-generated"
    message["X-Auto-Response-Suppress"] = "All"
    message.set_content(content.text)
    message.add_alternative(content.html, subtype="html")
    return message


def _finish_without_send(
    db: Session, row: EmailOutbox, status: str, reason: str, now: datetime
) -> None:
    row.status = status
    row.lease_expires_at = None
    row.locked_by = None
    if status == m.FAILED_PERMANENT:
        row.last_error_code = reason
    else:
        row.cancel_reason = reason
        row.cancelled_at = now
    _audit(
        db,
        WORKER_ACTOR,
        "reminder.delivery_cancelled"
        if status != m.FAILED_PERMANENT
        else "reminder.delivery_failed",
        {
            "outbox_id": str(row.id),
            "status": status,
            "reason": reason,
            "scheduled_date": row.scheduled_date.isoformat(),
            "days_offset": row.days_offset,
            "recipient": mask_email(row.recipient_email),
        },
    )


def claim_next(db: Session, *, worker: str, now: datetime | None = None) -> Claim | None | bool:
    """Claim one due row. Returns a Claim, True (a row was handled without
    sending, e.g. cancelled), or None (nothing due). Commits."""
    now = now or clock.utcnow()
    today = business_today(now)
    try:
        row = db.scalar(
            select(EmailOutbox)
            .where(
                EmailOutbox.status.in_(m.OPEN_STATUSES),
                EmailOutbox.next_attempt_at <= now,
            )
            .order_by(EmailOutbox.next_attempt_at, EmailOutbox.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            db.rollback()
            return None
        settings = get_reminder_settings(db)
        problem = _ineligibility(db, row, settings, today)
        if problem is not None:
            _finish_without_send(db, row, problem[0], problem[1], now)
            db.commit()
            return True
        email_row = email_svc.get_email_settings(db)
        assert email_row is not None
        try:
            config = email_svc.load_smtp_config(email_row)
        except AppError as exc:
            _finish_without_send(db, row, m.FAILED_PERMANENT, exc.code, now)
            db.commit()
            return True
        subscription = db.get(AppSubscription, row.subscription_id)
        assert subscription is not None
        message = build_message(db, row, subscription, today)

        row.status = m.PROCESSING
        row.attempt_count += 1
        row.last_attempt_at = now
        row.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        row.locked_by = worker
        row.message_id = str(message["Message-ID"])
        row.subject = str(message["Subject"])[:200]
        db.add(
            EmailDeliveryAttempt(
                id=uuid.uuid4(),
                outbox_id=row.id,
                attempt_number=row.attempt_count,
                outcome=m.ATTEMPT_IN_PROGRESS,
                worker=worker,
                started_at=now,
            )
        )
        claim = Claim(row.id, row.attempt_count, worker, config, message)
        db.commit()  # the attempt is durable before any SMTP traffic
        return claim
    except Exception:
        db.rollback()
        raise


def _backoff(attempt_number: int) -> timedelta:
    index = min(attempt_number - 1, len(BACKOFF_SECONDS) - 1)
    return timedelta(seconds=BACKOFF_SECONDS[index])


def deliver(db: Session, claim: Claim, transport: SmtpTransport) -> str:
    """Send one claimed message and record the outcome. Returns the new status."""
    transient = False
    code: str | None = None
    try:
        transport.send(claim.config, claim.message)
        ok = True
    except SmtpFailure as exc:
        ok, code, transient = False, exc.code, exc.transient
    except Exception:
        logger.exception("unexpected SMTP transport error")
        ok, code, transient = False, "smtp_error", True

    now = clock.utcnow()
    try:
        row = db.scalar(
            select(EmailOutbox).where(EmailOutbox.id == claim.outbox_id).with_for_update()
        )
        attempt = db.scalar(
            select(EmailDeliveryAttempt).where(
                EmailDeliveryAttempt.outbox_id == claim.outbox_id,
                EmailDeliveryAttempt.attempt_number == claim.attempt_number,
            )
        )
        assert row is not None and attempt is not None
        attempt.finished_at = now
        attempt.error_code = code
        if ok:
            attempt.outcome = m.ATTEMPT_ACCEPTED
        else:
            attempt.outcome = m.ATTEMPT_TRANSIENT if transient else m.ATTEMPT_PERMANENT

        still_ours = (
            row.status == m.PROCESSING
            and row.locked_by == claim.worker
            and row.attempt_count == claim.attempt_number
        )
        if not still_ours:
            # The lease was recovered meanwhile; keep the newer state, but an
            # acceptance is still the most important fact to record.
            if ok and row.status != m.ACCEPTED:
                row.status = m.ACCEPTED
                row.accepted_at = now
                row.last_error_code = None
        elif ok:
            row.status = m.ACCEPTED
            row.accepted_at = now
            row.last_error_code = None
        elif transient and row.attempt_count < row.max_attempts:
            row.status = m.RETRY_SCHEDULED
            row.next_attempt_at = now + _backoff(row.attempt_count)
            row.last_error_code = code
        else:
            # Permanent rejection, or a transient error on the last allowed attempt.
            row.status = m.FAILED_PERMANENT
            row.last_error_code = code
        if row.status != m.PROCESSING:
            row.lease_expires_at = None
            row.locked_by = None
        _audit(
            db,
            WORKER_ACTOR,
            "reminder.delivery_attempted",
            {
                "outbox_id": str(row.id),
                "attempt": claim.attempt_number,
                "outcome": attempt.outcome,
                "error_code": code,
                "status": row.status,
                "final": row.status in (m.ACCEPTED, m.FAILED_PERMANENT),
                "scheduled_date": row.scheduled_date.isoformat(),
                "days_offset": row.days_offset,
                "recipient": mask_email(row.recipient_email),
            },
        )
        status = row.status
        db.commit()
    except Exception:
        db.rollback()
        raise
    logger.info(
        "reminder %s attempt %s: %s (%s)", claim.outbox_id, claim.attempt_number, status, code
    )
    return status


def recover_expired_leases(db: Session, *, now: datetime | None = None) -> int:
    """Rows left in ``processing`` by a crashed worker: outcome unknown -> retry."""
    now = now or clock.utcnow()
    try:
        rows = db.scalars(
            select(EmailOutbox)
            .where(EmailOutbox.status == m.PROCESSING, EmailOutbox.lease_expires_at < now)
            .with_for_update(skip_locked=True)
        ).all()
        for row in rows:
            attempt = db.scalar(
                select(EmailDeliveryAttempt).where(
                    EmailDeliveryAttempt.outbox_id == row.id,
                    EmailDeliveryAttempt.attempt_number == row.attempt_count,
                )
            )
            if attempt is not None and attempt.outcome == m.ATTEMPT_IN_PROGRESS:
                attempt.outcome = m.ATTEMPT_UNCERTAIN
                attempt.error_code = "worker_interrupted"
                attempt.finished_at = now
            row.last_error_code = "delivery_outcome_unknown"
            row.lease_expires_at = None
            row.locked_by = None
            if row.attempt_count < row.max_attempts:
                row.status = m.RETRY_SCHEDULED
                row.next_attempt_at = now
            else:
                row.status = m.FAILED_PERMANENT
            _audit(
                db,
                WORKER_ACTOR,
                "reminder.delivery_interrupted",
                {
                    "outbox_id": str(row.id),
                    "attempt": row.attempt_count,
                    "status": row.status,
                    "recipient": mask_email(row.recipient_email),
                },
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    if rows:
        logger.warning("recovered %s interrupted reminder deliveries", len(rows))
    return len(rows)


@dataclass
class DispatchResult:
    recovered: int = 0
    handled: int = 0
    statuses: dict[str, int] = field(default_factory=dict)


def dispatch_due(
    session_factory: Callable[[], Session],
    transport: SmtpTransport,
    *,
    worker: str | None = None,
    limit: int = DISPATCH_BATCH,
) -> DispatchResult:
    worker = worker or worker_id()
    out = DispatchResult()
    with session_factory() as db:
        out.recovered = recover_expired_leases(db)
    for _ in range(limit):
        with session_factory() as db:
            claim = claim_next(db, worker=worker)
            if claim is None:
                break
            out.handled += 1
            if isinstance(claim, bool):
                out.statuses["not_sent"] = out.statuses.get("not_sent", 0) + 1
                continue
            status = deliver(db, claim, transport)
            out.statuses[status] = out.statuses.get(status, 0) + 1
    return out
