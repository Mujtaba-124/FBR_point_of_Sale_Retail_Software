"""Subscription expiry reminders: settings, durable email outbox, delivery attempts.

PostgreSQL is the source of truth for all pending email work; Redis/Celery only
carry "wake up and look at the outbox" signals.
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SINGLETON_ID = 1

# Outbox statuses.
PENDING = "pending"
PROCESSING = "processing"
RETRY_SCHEDULED = "retry_scheduled"
ACCEPTED = "accepted"  # accepted by the SMTP server (not proof of inbox delivery)
FAILED_PERMANENT = "failed_permanent"
CANCELLED_OBSOLETE = "cancelled_obsolete"  # subscription renewed; old schedule
CANCELLED = "cancelled"  # no longer eligible (see cancel_reason)

OUTBOX_STATUSES = (
    PENDING,
    PROCESSING,
    RETRY_SCHEDULED,
    ACCEPTED,
    FAILED_PERMANENT,
    CANCELLED_OBSOLETE,
    CANCELLED,
)
OPEN_STATUSES = (PENDING, RETRY_SCHEDULED)

# Delivery attempt outcomes.
ATTEMPT_IN_PROGRESS = "in_progress"
ATTEMPT_ACCEPTED = "accepted"
ATTEMPT_TRANSIENT = "transient_failure"
ATTEMPT_PERMANENT = "permanent_failure"
ATTEMPT_UNCERTAIN = "uncertain"  # worker stopped mid-attempt; outcome unknown

ATTEMPT_OUTCOMES = (
    ATTEMPT_IN_PROGRESS,
    ATTEMPT_ACCEPTED,
    ATTEMPT_TRANSIENT,
    ATTEMPT_PERMANENT,
    ATTEMPT_UNCERTAIN,
)

KIND_SUBSCRIPTION_REMINDER = "subscription_reminder"

DAYS_BEFORE = 15
DAYS_AFTER = 5


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class SubscriptionReminderSettings(Base):
    """Single-row reminder preferences plus the latest scheduler run summary."""

    __tablename__ = "subscription_reminder_settings"
    __table_args__ = (
        CheckConstraint(f"id = {SINGLETON_ID}", name="ck_reminder_settings_singleton"),
    )

    id: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, default=SINGLETON_ID, server_default=text("1")
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    notify_super_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    notify_company_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_business_date: Mapped[date | None] = mapped_column(Date)
    last_run_result: Mapped[str | None] = mapped_column(String(48))
    last_run_details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class EmailOutbox(Base):
    """One durable email job. Rows are never deleted; terminal states are kept as history.

    The unique constraint is the reminder's stable identity: the same reminder
    for the same recipient can exist only once, however often the scheduler
    runs or how many workers there are.
    """

    __tablename__ = "email_outbox"
    __table_args__ = (
        UniqueConstraint(
            "kind",
            "subscription_id",
            "expiry_date",
            "days_offset",
            "scheduled_date",
            "recipient_email",
            name="uq_email_outbox_reminder_identity",
        ),
        CheckConstraint(f"status IN ({_in(OUTBOX_STATUSES)})", name="ck_email_outbox_status"),
        CheckConstraint(f"kind IN ('{KIND_SUBSCRIPTION_REMINDER}')", name="ck_email_outbox_kind"),
        CheckConstraint(
            f"days_offset BETWEEN -{DAYS_BEFORE} AND {DAYS_AFTER}",
            name="ck_email_outbox_days_offset",
        ),
        CheckConstraint(
            "scheduled_date = expiry_date + days_offset", name="ck_email_outbox_schedule"
        ),
        CheckConstraint("attempt_count >= 0", name="ck_email_outbox_attempt_count"),
        CheckConstraint("recipient_email = lower(recipient_email)", name="ck_email_outbox_email"),
        Index("ix_email_outbox_due", "status", "next_attempt_at"),
        Index("ix_email_outbox_scheduled_date", "scheduled_date"),
        Index("ix_email_outbox_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    subscription_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("app_subscription.id", ondelete="RESTRICT"), nullable=False
    )
    # The expiry date this reminder was scheduled for (the schedule "version").
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    days_offset: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)
    recipient_categories: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=PENDING)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(200))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(48))
    message_id: Mapped[str | None] = mapped_column(String(255))
    subject: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class EmailDeliveryAttempt(Base):
    """One SMTP attempt for an outbox row (history; never deleted)."""

    __tablename__ = "email_delivery_attempts"
    __table_args__ = (
        UniqueConstraint("outbox_id", "attempt_number", name="uq_email_delivery_attempt_number"),
        CheckConstraint(
            f"outcome IN ({_in(ATTEMPT_OUTCOMES)})", name="ck_email_delivery_attempt_outcome"
        ),
        CheckConstraint("attempt_number >= 1", name="ck_email_delivery_attempt_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outbox_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_outbox.id", ondelete="RESTRICT"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    worker: Mapped[str | None] = mapped_column(String(200))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
