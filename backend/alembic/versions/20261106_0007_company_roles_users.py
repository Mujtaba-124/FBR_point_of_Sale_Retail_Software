"""Company User Management: roles, permissions, setup links, 15-account limit.

Additive and data-preserving:
- New tables ``company_roles``, ``company_role_permissions`` and
  ``password_setup_tokens``.
- Two protected system roles (Company Admin, Company User).
- New nullable/defaulted columns on ``users``; existing Company accounts are
  linked to the matching system role. No credentials or existing values change.
- A trigger that refuses a 16th active Company Workspace account, serialized
  with a transaction-level advisory lock so concurrent writes cannot pass it.

Revision ID: 0007_company_users
Revises: 0006_reminders
Create Date: 2026-11-06
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0007_company_users"
down_revision = "0006_reminders"
branch_labels = None
depends_on = None

MAX_ACTIVE_COMPANY_ACCOUNTS = 15
LIMIT_LOCK_KEY = 4801500015  # shared with app.services.company_users


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
        "company_roles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("description", sa.String(300)),
        sa.Column("system_key", sa.String(32), unique=True),
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
        *_timestamps(),
        sa.CheckConstraint("length(trim(name)) >= 2", name="ck_company_roles_name"),
        sa.CheckConstraint(
            "system_key IS NULL OR system_key IN ('company_admin', 'company_user')",
            name="ck_company_roles_system_key",
        ),
    )
    op.create_index(
        "uq_company_roles_name_lower", "company_roles", [sa.text("lower(name)")], unique=True
    )

    op.create_table(
        "company_role_permissions",
        sa.Column(
            "role_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("company_roles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("permission", sa.String(64), primary_key=True),
        sa.Column(
            "granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            r"permission ~ '^[a-z_]+\.[a-z_]+$'", name="ck_company_role_permissions_key"
        ),
    )

    op.execute(
        """
        INSERT INTO company_roles (name, description, system_key) VALUES
          ('Company Admin',
           'Protected administrator with full Company Workspace access.', 'company_admin'),
          ('Company User',
           'Default role for company staff: Dashboard only.', 'company_user')
        """
    )
    op.execute(
        """
        INSERT INTO company_role_permissions (role_id, permission)
        SELECT id, 'dashboard.view' FROM company_roles WHERE system_key = 'company_user'
        """
    )

    op.add_column(
        "users",
        sa.Column(
            "company_role_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("company_roles.id", ondelete="RESTRICT"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "must_set_password", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.create_index("ix_users_company_role_id", "users", ["company_role_id"])
    # Link existing Company accounts to their system role (credentials untouched).
    op.execute(
        """
        UPDATE users u SET company_role_id = r.id
        FROM company_roles r
        WHERE r.system_key = u.access_category::text
          AND u.access_category IN ('company_admin', 'company_user')
        """
    )
    # Accounts created by other paths (bootstrap CLI) get their system role.
    op.execute(
        """
        CREATE FUNCTION assign_default_company_role() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.company_role_id IS NULL
               AND NEW.access_category IN ('company_admin', 'company_user') THEN
                SELECT id INTO NEW.company_role_id FROM company_roles
                 WHERE system_key = NEW.access_category::text;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_assign_default_company_role
        BEFORE INSERT ON users
        FOR EACH ROW EXECUTE FUNCTION assign_default_company_role()
        """
    )
    op.create_check_constraint(
        "ck_users_company_role",
        "users",
        "(access_category = 'super_admin') = (company_role_id IS NULL)",
    )

    op.create_table(
        "password_setup_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_password_setup_tokens_user_id", "password_setup_tokens", ["user_id"])

    op.execute(
        f"""
        CREATE FUNCTION enforce_company_account_limit() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            active_count integer;
        BEGIN
            -- Serialize every write that can add an active Company account.
            PERFORM pg_advisory_xact_lock({LIMIT_LOCK_KEY});
            SELECT count(*) INTO active_count FROM users
             WHERE is_active AND access_category IN ('company_admin', 'company_user');
            IF active_count > {MAX_ACTIVE_COMPANY_ACCOUNTS} THEN
                RAISE EXCEPTION 'company_user_limit_reached'
                    USING ERRCODE = 'check_violation',
                          DETAIL = 'At most {MAX_ACTIVE_COMPANY_ACCOUNTS} active Company accounts.';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_company_account_limit
        AFTER INSERT OR UPDATE OF is_active, access_category ON users
        FOR EACH ROW
        WHEN (NEW.is_active AND NEW.access_category IN ('company_admin', 'company_user'))
        EXECUTE FUNCTION enforce_company_account_limit()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_company_account_limit ON users")
    op.execute("DROP FUNCTION IF EXISTS enforce_company_account_limit()")
    op.drop_index("ix_password_setup_tokens_user_id", table_name="password_setup_tokens")
    op.drop_table("password_setup_tokens")
    op.drop_constraint("ck_users_company_role", "users", type_="check")
    op.execute("DROP TRIGGER IF EXISTS trg_assign_default_company_role ON users")
    op.execute("DROP FUNCTION IF EXISTS assign_default_company_role()")
    op.drop_index("ix_users_company_role_id", table_name="users")
    op.drop_column("users", "must_set_password")
    op.drop_column("users", "company_role_id")
    op.drop_table("company_role_permissions")
    op.drop_index("uq_company_roles_name_lower", table_name="company_roles")
    op.drop_table("company_roles")
