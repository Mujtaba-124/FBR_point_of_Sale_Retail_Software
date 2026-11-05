"""Subscription renewal history: subscription_renewals (append-only).

Additive only: creates one table, its indexes, and a trigger function that
rejects UPDATE/DELETE on that new table. Existing tables and rows are not
touched.

Revision ID: 0004_renewals
Revises: 0003_subscription
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004_renewals"
down_revision = "0003_subscription"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscription_renewals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "subscription_id",
            sa.SmallInteger(),
            sa.ForeignKey("app_subscription.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("previous_expiry_date", sa.Date(), nullable=False),
        sa.Column("new_expiry_date", sa.Date(), nullable=False),
        sa.Column(
            "renewed_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("renewal_note", sa.String(500)),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column(
            "renewed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "new_expiry_date > previous_expiry_date", name="ck_subscription_renewals_extends"
        ),
    )
    op.create_index(
        "ix_subscription_renewals_renewed_at", "subscription_renewals", ["renewed_at"]
    )
    op.create_index(
        "ix_subscription_renewals_subscription_id", "subscription_renewals", ["subscription_id"]
    )
    op.execute(
        """
        CREATE FUNCTION subscription_renewals_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'subscription_renewals is append-only (% is not allowed)', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_subscription_renewals_append_only
        BEFORE UPDATE OR DELETE ON subscription_renewals
        FOR EACH ROW EXECUTE FUNCTION subscription_renewals_append_only();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_subscription_renewals_append_only ON subscription_renewals"
    )
    op.execute("DROP FUNCTION IF EXISTS subscription_renewals_append_only()")
    op.drop_index("ix_subscription_renewals_subscription_id", table_name="subscription_renewals")
    op.drop_index("ix_subscription_renewals_renewed_at", table_name="subscription_renewals")
    op.drop_table("subscription_renewals")
