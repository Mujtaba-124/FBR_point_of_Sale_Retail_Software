"""Authentication: users and authentication_sessions.

Additive only: creates one enum type, two tables and their indexes.
No existing objects are altered or dropped.

Revision ID: 0001_auth
Revises:
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001_auth"
down_revision = None
branch_labels = None
depends_on = None

access_category = postgresql.ENUM(
    "super_admin", "company_admin", "company_user", name="access_category", create_type=False
)


def upgrade() -> None:
    access_category.create(op.get_bind(), checkfirst=False)

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("access_category", access_category, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True
    )
    op.create_index("ix_users_access_category", "users", ["access_category"])

    op.create_table(
        "authentication_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("csrf_token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("user_agent", sa.String(255)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_authentication_sessions_user_id", "authentication_sessions", ["user_id"]
    )
    op.create_index(
        "ix_authentication_sessions_expires_at", "authentication_sessions", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_authentication_sessions_expires_at", table_name="authentication_sessions")
    op.drop_index("ix_authentication_sessions_user_id", table_name="authentication_sessions")
    op.drop_table("authentication_sessions")
    op.drop_index("ix_users_access_category", table_name="users")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_table("users")
    access_category.drop(op.get_bind(), checkfirst=False)
