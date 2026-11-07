"""Excel sales uploads: batches, append-only revisions and sales records.

Additive only: three new tables, no change to existing rows.
- upload_batches: one current upload per (shop_id, sales_date), UNIQUE.
- upload_revisions / sales_records: append-only (UPDATE/DELETE refused by
  trigger); a Draft replacement adds a revision instead of overwriting.
Money is NUMERIC; uploaded values are stored as validated, never recomputed.

Revision ID: 0011_sales_uploads
Revises: 0010_user_shop_access
Create Date: 2026-11-07
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0011_sales_uploads"
down_revision = "0010_user_shop_access"
branch_labels = None
depends_on = None

APPEND_ONLY = """
CREATE FUNCTION sales_uploads_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$;
"""

MONEY = sa.Numeric(14, 2)


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def _user_fk(name: str) -> sa.Column:
    return sa.Column(
        name, postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")
    )


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


def upgrade() -> None:
    op.create_table(
        "upload_batches",
        _uuid_pk(),
        sa.Column(
            "shop_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shops.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("sales_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("total_records", sa.Integer(), nullable=False),
        sa.Column("total_amount", MONEY, nullable=False),
        sa.Column("total_sales_tax", MONEY, nullable=False),
        sa.Column("total_net_amount", MONEY, nullable=False),
        _user_fk("created_by_user_id"),
        _user_fk("updated_by_user_id"),
        _created_at(),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("shop_id", "sales_date", name="uq_upload_batches_shop_date"),
        sa.CheckConstraint(
            "status IN ('draft', 'wait_for_approval', 'accepted', 'rejected')",
            name="ck_upload_batches_status",
        ),
        sa.CheckConstraint("current_revision >= 1", name="ck_upload_batches_revision"),
        sa.CheckConstraint("total_records >= 1", name="ck_upload_batches_records"),
    )
    op.create_index("ix_upload_batches_sales_date", "upload_batches", ["sales_date"])
    op.create_index("ix_upload_batches_status", "upload_batches", ["status"])

    op.create_table(
        "upload_revisions",
        _uuid_pk(),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("upload_batches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(200), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("total_records", sa.Integer(), nullable=False),
        sa.Column("total_amount", MONEY, nullable=False),
        sa.Column("total_sales_tax", MONEY, nullable=False),
        sa.Column("total_net_amount", MONEY, nullable=False),
        _user_fk("uploaded_by_user_id"),
        _created_at(),
        sa.UniqueConstraint("batch_id", "revision_number", name="uq_upload_revisions_number"),
        sa.UniqueConstraint("storage_key", name="uq_upload_revisions_storage_key"),
        sa.CheckConstraint("revision_number >= 1", name="ck_upload_revisions_number"),
        sa.CheckConstraint("file_size > 0", name="ck_upload_revisions_size"),
        sa.CheckConstraint("total_records >= 1", name="ck_upload_revisions_records"),
        sa.CheckConstraint(
            "checksum_sha256 ~ '^[0-9a-f]{64}$'", name="ck_upload_revisions_checksum"
        ),
    )

    op.create_table(
        "sales_records",
        _uuid_pk(),
        sa.Column(
            "revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("upload_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("upload_batches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "shop_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shops.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("excel_row", sa.Integer(), nullable=False),
        sa.Column("sale_date", sa.Date(), nullable=False),
        sa.Column("sale_time", sa.Time(), nullable=False),
        sa.Column("customer_name", sa.Text()),
        sa.Column("cnic_ntn", sa.String(20)),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("rate", sa.Numeric(16, 4), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("tax_percent", sa.Numeric(7, 4), nullable=False),
        sa.Column("tax_amount", MONEY, nullable=False),
        sa.Column("net_amount", MONEY, nullable=False),
        _created_at(),
        sa.UniqueConstraint("revision_id", "excel_row", name="uq_sales_records_revision_row"),
        sa.CheckConstraint("quantity > 0", name="ck_sales_records_quantity"),
        sa.CheckConstraint("rate >= 0", name="ck_sales_records_rate"),
        sa.CheckConstraint("amount >= 0", name="ck_sales_records_amount"),
        sa.CheckConstraint(
            "tax_percent >= 0 AND tax_percent <= 100", name="ck_sales_records_tax_pct"
        ),
        sa.CheckConstraint("tax_amount >= 0", name="ck_sales_records_tax"),
        sa.CheckConstraint("net_amount >= 0", name="ck_sales_records_net"),
    )
    op.create_index("ix_sales_records_shop_date", "sales_records", ["shop_id", "sale_date"])

    op.execute(APPEND_ONLY)
    for table in ("upload_revisions", "sales_records"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION sales_uploads_append_only()"
        )


def downgrade() -> None:
    for table in ("sales_records", "upload_revisions"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS sales_uploads_append_only()")
    op.drop_index("ix_sales_records_shop_date", table_name="sales_records")
    op.drop_table("sales_records")
    op.drop_table("upload_revisions")
    op.drop_index("ix_upload_batches_status", table_name="upload_batches")
    op.drop_index("ix_upload_batches_sales_date", table_name="upload_batches")
    op.drop_table("upload_batches")
