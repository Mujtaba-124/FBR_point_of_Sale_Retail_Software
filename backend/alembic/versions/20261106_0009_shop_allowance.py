"""Shop Allowance: Super Admin-controlled limit on registered shops.

Additive only:
- new singleton table ``shop_allowance`` seeded as Unlimited, which preserves
  the existing no-limit behaviour (no allowance existed before this revision);
- a BEFORE INSERT trigger on ``shops`` that enforces the allowance for every
  write path, including raw SQL.

No existing row in ``shops`` (or any other table) is read-modified or deleted.

Lock order (deadlock-free): the only lock taken is the ``shop_allowance`` row,
FOR UPDATE, first. The application takes it before inserting a shop and before
changing the allowance; the trigger takes it again (a no-op in the same
transaction) so alternate write paths are serialized the same way. Active and
inactive shops both count; deactivation never frees a slot.

Revision ID: 0009_shop_allowance
Revises: 0008_shops
Create Date: 2026-11-06
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0009_shop_allowance"
down_revision = "0008_shops"
branch_labels = None
depends_on = None

ENFORCE_FUNCTION = """
CREATE FUNCTION shops_enforce_allowance() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    allowance_mode text;
    allowance_max integer;
    registered bigint;
BEGIN
    SELECT mode, max_shops INTO allowance_mode, allowance_max
      FROM shop_allowance WHERE id = 1 FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'shop_limit_reached: no shop allowance is configured'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'shops_within_allowance';
    END IF;
    IF allowance_mode = 'limited' THEN
        SELECT count(*) INTO registered FROM shops;
        IF registered >= allowance_max THEN
            RAISE EXCEPTION 'shop_limit_reached: % of % shops registered', registered, allowance_max
                USING ERRCODE = 'check_violation', CONSTRAINT = 'shops_within_allowance';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
"""

PROTECT_FUNCTION = """
CREATE FUNCTION shop_allowance_no_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'the shop allowance row cannot be deleted'
        USING ERRCODE = 'restrict_violation';
END;
$$;
"""


def upgrade() -> None:
    op.create_table(
        "shop_allowance",
        sa.Column("id", sa.SmallInteger(), primary_key=True, server_default=sa.text("1")),
        sa.Column("mode", sa.String(16), nullable=False, server_default="unlimited"),
        sa.Column("max_shops", sa.Integer()),
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
        sa.CheckConstraint("id = 1", name="ck_shop_allowance_singleton"),
        sa.CheckConstraint(
            "(mode = 'limited' AND max_shops IS NOT NULL AND max_shops >= 1) OR "
            "(mode = 'unlimited' AND max_shops IS NULL)",
            name="ck_shop_allowance_mode",
        ),
        sa.CheckConstraint("version >= 1", name="ck_shop_allowance_version"),
    )
    # Initial state: Unlimited, matching the behaviour before this revision.
    op.execute(
        "INSERT INTO shop_allowance (id, mode, max_shops, version) VALUES (1, 'unlimited', NULL, 1)"
    )
    op.execute(PROTECT_FUNCTION)
    op.execute(
        "CREATE TRIGGER shop_allowance_no_delete BEFORE DELETE ON shop_allowance "
        "FOR EACH ROW EXECUTE FUNCTION shop_allowance_no_delete()"
    )
    op.execute(ENFORCE_FUNCTION)
    op.execute(
        "CREATE TRIGGER shops_enforce_allowance BEFORE INSERT ON shops "
        "FOR EACH ROW EXECUTE FUNCTION shops_enforce_allowance()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS shops_enforce_allowance ON shops")
    op.execute("DROP FUNCTION IF EXISTS shops_enforce_allowance()")
    op.execute("DROP TRIGGER IF EXISTS shop_allowance_no_delete ON shop_allowance")
    op.execute("DROP FUNCTION IF EXISTS shop_allowance_no_delete()")
    op.drop_table("shop_allowance")
