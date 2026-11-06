"""User shop access: which shops each Company User may work with.

Additive only:
- ``user_shop_access`` (one row per Company User: none / selected / all)
- ``user_shop_assignments`` (user x shop, only while the mode is 'selected')
- deferred constraint triggers that keep the two consistent

Existing data: every existing Company User gets an explicit 'none' row (No Shop
Access) - nobody silently gains shop access. The protected Company Admin gets
no row: its company-wide scope comes from its tier. No assignment is backfilled.
No existing row in any other table is changed.

Revision ID: 0010_user_shop_access
Revises: 0009_shop_allowance
Create Date: 2026-11-06
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0010_user_shop_access"
down_revision = "0009_shop_allowance"
branch_labels = None
depends_on = None

# Runs at COMMIT (deferred), after the whole save has been applied.
CHECK_ACCESS = """
CREATE FUNCTION user_shop_access_check() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    target uuid;
BEGIN
    IF TG_TABLE_NAME = 'user_shop_access' THEN
        target := NEW.user_id;
        IF NOT EXISTS (
            SELECT 1 FROM users WHERE id = target AND access_category = 'company_user'
        ) THEN
            RAISE EXCEPTION 'shop access rows are for Company Users only'
                USING ERRCODE = 'check_violation', CONSTRAINT = 'user_shop_access_company_user';
        END IF;
    ELSE
        target := OLD.user_id;
    END IF;
    IF EXISTS (
        SELECT 1 FROM user_shop_access a
        WHERE a.user_id = target AND a.access_mode = 'selected'
          AND NOT EXISTS (SELECT 1 FROM user_shop_assignments s WHERE s.user_id = target)
    ) THEN
        RAISE EXCEPTION 'selected shop access needs at least one shop'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'user_shop_access_selected_nonempty';
    END IF;
    RETURN NULL;
END;
$$;
"""


def upgrade() -> None:
    op.create_table(
        "user_shop_access",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("access_mode", sa.String(16), nullable=False, server_default="none"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
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
        sa.CheckConstraint(
            "access_mode IN ('none', 'selected', 'all')", name="ck_user_shop_access_mode"
        ),
        sa.CheckConstraint("version >= 1", name="ck_user_shop_access_version"),
        sa.UniqueConstraint("user_id", "access_mode", name="uq_user_shop_access_user_mode"),
    )
    op.create_table(
        "user_shop_assignments",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "shop_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shops.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "access_mode", sa.String(16), nullable=False, server_default=sa.text("'selected'")
        ),
        sa.Column(
            "assigned_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("access_mode = 'selected'", name="ck_user_shop_assignments_mode"),
        sa.ForeignKeyConstraint(
            ["user_id", "access_mode"],
            ["user_shop_access.user_id", "user_shop_access.access_mode"],
            name="fk_user_shop_assignments_access",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_user_shop_assignments_shop_id", "user_shop_assignments", ["shop_id"])

    op.execute(CHECK_ACCESS)
    op.execute(
        "CREATE CONSTRAINT TRIGGER user_shop_access_check AFTER INSERT OR UPDATE "
        "ON user_shop_access DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION user_shop_access_check()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER user_shop_assignments_check AFTER DELETE "
        "ON user_shop_assignments DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION user_shop_access_check()"
    )

    # Existing Company Users: explicit No Shop Access. Nobody gains access silently.
    op.execute(
        "INSERT INTO user_shop_access (user_id, access_mode, version) "
        "SELECT id, 'none', 1 FROM users WHERE access_category = 'company_user'"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS user_shop_assignments_check ON user_shop_assignments")
    op.execute("DROP TRIGGER IF EXISTS user_shop_access_check ON user_shop_access")
    op.execute("DROP FUNCTION IF EXISTS user_shop_access_check()")
    op.drop_index("ix_user_shop_assignments_shop_id", table_name="user_shop_assignments")
    op.drop_table("user_shop_assignments")
    op.drop_table("user_shop_access")
