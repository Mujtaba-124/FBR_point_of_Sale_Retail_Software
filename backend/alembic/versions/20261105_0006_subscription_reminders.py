"""Subscription expiry reminders: settings, durable email outbox, delivery attempts.

Additive only: three new tables and one default settings row (reminders
DISABLED). No existing table or row changes.

Revision ID: 0006_reminders
Revises: 0005_email_settings
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006_reminders"
down_revision = "0005_email_settings"
branch_labels = None
depends_on = None

_STATUSES = (
    "'pending', 'processing', 'retry_scheduled', 'accepted', 'failed_permanent', "
    "'cancelled_obsolete', 'cancelled'"
)
_OUTCOMES = "'in_progress', 'accepted', 'transient_failure', 'permanent_failure', 'uncertain'"


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "subscription_reminder_settings",
        sa.Column("id", sa.SmallInteger(), primary_key=True, server_default=sa.text("1")),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "notify_super_admin", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "notify_company_admin", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_run_business_date", sa.Date()),
        sa.Column("last_run_result", sa.String(48)),
        sa.Column(
            "last_run_details",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "updated_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        *_timestamps(),
        sa.CheckConstraint("id = 1", name="ck_reminder_settings_singleton"),
    )
    # The single settings row, reminders disabled until a Super Admin enables them.
    op.execute("INSERT INTO subscription_reminder_settings (id) VALUES (1)")

    op.create_table(
        "email_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column(
            "subscription_id",
            sa.SmallInteger(),
            sa.ForeignKey("app_subscription.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("days_offset", sa.SmallInteger(), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("recipient_email", sa.String(320), nullable=False),
        sa.Column("recipient_categories", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("locked_by", sa.String(200)),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_reason", sa.String(48)),
        sa.Column("message_id", sa.String(255)),
        sa.Column("subject", sa.String(200)),
        *_timestamps(),
        sa.UniqueConstraint(
            "kind",
            "subscription_id",
            "expiry_date",
            "days_offset",
            "scheduled_date",
            "recipient_email",
            name="uq_email_outbox_reminder_identity",
        ),
        sa.CheckConstraint(f"status IN ({_STATUSES})", name="ck_email_outbox_status"),
        sa.CheckConstraint("kind IN ('subscription_reminder')", name="ck_email_outbox_kind"),
        sa.CheckConstraint("days_offset BETWEEN -15 AND 5", name="ck_email_outbox_days_offset"),
        sa.CheckConstraint(
            "scheduled_date = expiry_date + days_offset", name="ck_email_outbox_schedule"
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_email_outbox_attempt_count"),
        sa.CheckConstraint(
            "recipient_email = lower(recipient_email)", name="ck_email_outbox_email"
        ),
    )
    op.create_index("ix_email_outbox_due", "email_outbox", ["status", "next_attempt_at"])
    op.create_index("ix_email_outbox_scheduled_date", "email_outbox", ["scheduled_date"])
    op.create_index("ix_email_outbox_created_at", "email_outbox", ["created_at"])

    op.create_table(
        "email_delivery_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "outbox_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("email_outbox.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("worker", sa.String(200)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("outbox_id", "attempt_number", name="uq_email_delivery_attempt_number"),
        sa.CheckConstraint(f"outcome IN ({_OUTCOMES})", name="ck_email_delivery_attempt_outcome"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_email_delivery_attempt_number"),
    )


def downgrade() -> None:
    op.drop_table("email_delivery_attempts")
    op.drop_index("ix_email_outbox_created_at", table_name="email_outbox")
    op.drop_index("ix_email_outbox_scheduled_date", table_name="email_outbox")
    op.drop_index("ix_email_outbox_due", table_name="email_outbox")
    op.drop_table("email_outbox")
    op.drop_table("subscription_reminder_settings")
