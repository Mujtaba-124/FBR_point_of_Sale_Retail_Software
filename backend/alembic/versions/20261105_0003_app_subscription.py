"""Single-company subscription: app_subscription.

Additive only: creates one table. No existing objects change and no rows are
inserted (an unconfigured subscription is shown as "Not Configured").

Revision ID: 0003_subscription
Revises: 0002_audit
Create Date: 2026-11-05
"""

import sqlalchemy as sa

from alembic import op

revision = "0003_subscription"
down_revision = "0002_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_subscription",
        sa.Column("id", sa.SmallInteger(), primary_key=True, server_default=sa.text("1")),
        sa.Column("company_name", sa.String(200), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("last_renewed_on", sa.Date()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("id = 1", name="ck_app_subscription_singleton"),
        sa.CheckConstraint("expiry_date >= start_date", name="ck_app_subscription_date_range"),
        sa.CheckConstraint(
            "length(trim(company_name)) > 0", name="ck_app_subscription_company_name"
        ),
    )


def downgrade() -> None:
    op.drop_table("app_subscription")
