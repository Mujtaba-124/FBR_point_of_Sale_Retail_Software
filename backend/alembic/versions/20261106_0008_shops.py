"""Shop Management: the ``shops`` table.

Additive only: one new table, no changes to existing tables or rows. FBR
tokens are stored only as AES-256-GCM ciphertext (separate FBR key, never in
the database). Shop Code and POS ID are unique case-insensitively.

Revision ID: 0008_shops
Revises: 0007_company_users
Create Date: 2026-11-06
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0008_shops"
down_revision = "0007_company_users"
branch_labels = None
depends_on = None

CODE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,19}$"
POS_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,49}$"


def upgrade() -> None:
    op.create_table(
        "shops",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("branch_name", sa.String(120), nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("pos_id", sa.String(50), nullable=False),
        sa.Column("encrypted_fbr_token", sa.Text()),
        sa.Column("fbr_token_updated_at", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
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
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_shops_name"),
        sa.CheckConstraint("length(trim(branch_name)) > 0", name="ck_shops_branch_name"),
        sa.CheckConstraint(f"code ~ '{CODE_PATTERN}'", name="ck_shops_code"),
        sa.CheckConstraint(f"pos_id ~ '{POS_ID_PATTERN}'", name="ck_shops_pos_id"),
        sa.CheckConstraint(
            "(encrypted_fbr_token IS NULL) = (fbr_token_updated_at IS NULL)",
            name="ck_shops_fbr_token_state",
        ),
    )
    op.create_index("uq_shops_code_lower", "shops", [sa.text("lower(code)")], unique=True)
    op.create_index("uq_shops_pos_id_lower", "shops", [sa.text("lower(pos_id)")], unique=True)
    op.create_index("ix_shops_is_active", "shops", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_shops_is_active", table_name="shops")
    op.drop_index("uq_shops_pos_id_lower", table_name="shops")
    op.drop_index("uq_shops_code_lower", table_name="shops")
    op.drop_table("shops")
