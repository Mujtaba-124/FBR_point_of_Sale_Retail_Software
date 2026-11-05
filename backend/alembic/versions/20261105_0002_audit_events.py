"""Audit trail: audit_events.

Additive only: creates one table and its indexes. No existing objects change.

Revision ID: 0002_audit
Revises: 0001_auth
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002_audit"
down_revision = "0001_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("target_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "details",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index("ix_audit_events_target_user_id", "audit_events", ["target_user_id"])
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_occurred_at", table_name="audit_events")
    op.drop_index("ix_audit_events_target_user_id", table_name="audit_events")
    op.drop_table("audit_events")
