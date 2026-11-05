"""Reminder API models: minimal, typed, no credentials, recipients masked."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.security import mask_email
from app.models import EmailOutbox
from app.models.reminders import DAYS_AFTER, DAYS_BEFORE
from app.services.reminder_schedule import ReminderStage
from app.services.reminder_settings import ReminderOverview, send_hour_label
from app.services.smtp_transport import FAILURE_MESSAGES

OutboxStatus = Literal[
    "pending",
    "processing",
    "retry_scheduled",
    "accepted",
    "failed_permanent",
    "cancelled_obsolete",
    "cancelled",
]

REASON_MESSAGES: dict[str, str] = {
    **FAILURE_MESSAGES,
    "delivery_outcome_unknown": (
        "The worker stopped during sending, so the result is unknown. The reminder was retried."
    ),
    "encryption_key_missing": "The server's email encryption key is not set up.",
    "stored_password_unreadable": "The saved SMTP password can no longer be decrypted.",
    "invalid_email_settings": "The saved SMTP settings are incomplete.",
    "subscription_renewed": "The subscription was renewed, so this reminder is no longer valid.",
    "schedule_changed": "The reminder schedule changed.",
    "reminders_disabled": "Reminders were disabled.",
    "email_sending_disabled": "Email sending was disabled.",
    "email_not_configured": "SMTP settings were not configured.",
    "subscription_not_configured": "No subscription is configured.",
    "missed_send_window": "Not sent on its scheduled date (sending was unavailable that day).",
    "recipient_not_eligible": "The recipient was no longer eligible (inactive or not selected).",
}


def reason_message(code: str | None) -> str | None:
    if code is None:
        return None
    return REASON_MESSAGES.get(code, "The reminder could not be sent.")


class ReminderSettingsOut(BaseModel):
    is_enabled: bool
    notify_super_admin: bool
    notify_company_admin: bool
    version: int
    updated_at: datetime


class ReminderScheduleOut(BaseModel):
    days_before: int = DAYS_BEFORE
    days_after: int = DAYS_AFTER
    send_time: str
    timezone: Literal["Asia/Karachi"] = "Asia/Karachi"
    expiry_date: date | None
    window_start: date | None
    window_end: date | None
    today: date
    today_stage: str | None
    next_reminder_date: date | None


class ReminderRecipientsOut(BaseModel):
    super_admin_status: Literal["selected", "none", "ambiguous", "invalid", "disabled"]
    super_admin_email: str | None  # masked
    company_admin_emails: list[str]  # masked
    company_admins_without_valid_email: int


class ReminderReadinessOut(BaseModel):
    email_configured: bool
    email_enabled: bool


class LastRunOut(BaseModel):
    at: datetime | None
    business_date: date | None
    result: str | None
    queued: int | None
    already_queued: int | None


class ReminderOverviewOut(BaseModel):
    settings: ReminderSettingsOut
    schedule: ReminderScheduleOut
    recipients: ReminderRecipientsOut
    readiness: ReminderReadinessOut
    last_run: LastRunOut

    @classmethod
    def build(cls, o: ReminderOverview) -> "ReminderOverviewOut":
        s = o.settings
        details = s.last_run_details or {}
        return cls(
            settings=ReminderSettingsOut(
                is_enabled=s.is_enabled,
                notify_super_admin=s.notify_super_admin,
                notify_company_admin=s.notify_company_admin,
                version=s.version,
                updated_at=s.updated_at,
            ),
            schedule=ReminderScheduleOut(
                send_time=send_hour_label(),
                expiry_date=o.expiry_date,
                window_start=o.window[0] if o.window else None,
                window_end=o.window[1] if o.window else None,
                today=o.today,
                today_stage=o.today_stage.label if o.today_stage else None,
                next_reminder_date=o.next_reminder_date,
            ),
            recipients=ReminderRecipientsOut(
                super_admin_status=o.resolution.super_admin_status,  # type: ignore[arg-type]
                super_admin_email=o.super_admin_email,
                company_admin_emails=o.company_admin_emails,
                company_admins_without_valid_email=o.resolution.skipped_company_admins,
            ),
            readiness=ReminderReadinessOut(
                email_configured=o.email_configured, email_enabled=o.email_enabled
            ),
            last_run=LastRunOut(
                at=s.last_run_at,
                business_date=s.last_run_business_date,
                result=s.last_run_result,
                queued=details.get("queued"),
                already_queued=details.get("already_queued"),
            ),
        )


class UpdateReminderSettingsRequest(BaseModel):
    is_enabled: bool
    notify_super_admin: bool
    notify_company_admin: bool
    expected_version: int = Field(ge=1)


class ReminderHistoryItemOut(BaseModel):
    id: str
    scheduled_date: date
    expiry_date: date
    days_offset: int
    stage: str
    recipient_categories: list[Literal["super_admin", "company_admin"]]
    recipient: str  # masked
    status: OutboxStatus
    attempt_count: int
    max_attempts: int
    last_attempt_at: datetime | None
    next_attempt_at: datetime | None
    accepted_at: datetime | None
    reason_code: str | None
    reason: str | None

    @classmethod
    def from_model(cls, row: EmailOutbox) -> "ReminderHistoryItemOut":
        code = row.cancel_reason if row.status.startswith("cancelled") else row.last_error_code
        return cls(
            id=str(row.id),
            scheduled_date=row.scheduled_date,
            expiry_date=row.expiry_date,
            days_offset=row.days_offset,
            stage=ReminderStage(row.days_offset).label,
            recipient_categories=row.recipient_categories,  # type: ignore[arg-type]
            recipient=mask_email(row.recipient_email),
            status=row.status,  # type: ignore[arg-type]
            attempt_count=row.attempt_count,
            max_attempts=row.max_attempts,
            last_attempt_at=row.last_attempt_at,
            next_attempt_at=row.next_attempt_at if row.status == "retry_scheduled" else None,
            accepted_at=row.accepted_at,
            reason_code=code,
            reason=reason_message(code),
        )


class ReminderHistoryOut(BaseModel):
    items: list[ReminderHistoryItemOut]
    total: int
    limit: int
    offset: int
    counts: dict[str, int]
