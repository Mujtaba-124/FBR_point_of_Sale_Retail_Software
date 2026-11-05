"""Email settings: email_settings (single-row SMTP configuration).

Additive only: creates one table. No existing objects change and no rows are
inserted. The SMTP password column holds ciphertext only; the encryption key
lives in the environment, never in the database.

Revision ID: 0005_email_settings
Revises: 0004_renewals
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005_email_settings"
down_revision = "0004_renewals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_settings",
        sa.Column("id", sa.SmallInteger(), primary_key=True, server_default=sa.text("1")),
        sa.Column("smtp_host", sa.String(253), nullable=False),
        sa.Column("smtp_port", sa.Integer(), nullable=False),
        sa.Column("encryption_mode", sa.String(16), nullable=False),
        sa.Column("smtp_username", sa.String(320)),
        sa.Column("encrypted_smtp_password", sa.Text()),
        sa.Column("sender_email", sa.String(320), nullable=False),
        sa.Column("sender_name", sa.String(100), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_test_status", sa.String(16)),
        sa.Column("last_test_kind", sa.String(16)),
        sa.Column("last_test_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_code", sa.String(64)),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "updated_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("id = 1", name="ck_email_settings_singleton"),
        sa.CheckConstraint(
            "encryption_mode IN ('starttls', 'ssl')", name="ck_email_settings_encryption_mode"
        ),
        sa.CheckConstraint("smtp_port BETWEEN 1 AND 65535", name="ck_email_settings_port"),
        sa.CheckConstraint(
            "last_test_status IS NULL OR last_test_status IN ('success', 'failure')",
            name="ck_email_settings_last_test_status",
        ),
        sa.CheckConstraint(
            "last_test_kind IS NULL OR last_test_kind IN ('connection', 'email')",
            name="ck_email_settings_last_test_kind",
        ),
    )


def downgrade() -> None:
    op.drop_table("email_settings")
