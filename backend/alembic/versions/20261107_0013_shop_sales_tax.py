"""Shop-wise Sales Tax % and the 8-column Excel template (Phase 4.2).

- ``shops.sales_tax_rate``: NUMERIC(5,2), 0-100. Existing shops get NULL
  ("Not configured"): no rate is assumed. New uploads need a configured rate.
- ``sales_records.item``: the sold item. NULL only for rows from the previous
  10-column template, which had no Item column (never invented).
- ``upload_revisions``: the immutable financial context of each revision:
  ``template_format`` (legacy_10col | standard_8col), ``applied_sales_tax_rate``
  and ``tax_rate_source`` (shop | draft | legacy_rows | legacy_mixed).

Existing revisions are legacy_10col. Their rows already store the tax % each
row was uploaded with; when all rows of a revision share one rate, that rate
becomes the revision's snapshot (``legacy_rows``). A revision with mixed rates
keeps NULL (``legacy_mixed``); its per-row rates stay authoritative.

Writing these snapshots is the only UPDATE: the append-only trigger is
disabled for that statement and re-enabled in the same transaction. No
financial value, uploaded value, file or checksum is touched.

Revision ID: 0013_shop_sales_tax
Revises: 0012_upload_uploader_restrict
Create Date: 2026-11-07
"""

import sqlalchemy as sa

from alembic import op

revision = "0013_shop_sales_tax"
down_revision = "0012_upload_uploader_restrict"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shops", sa.Column("sales_tax_rate", sa.Numeric(5, 2), nullable=True))
    op.create_check_constraint(
        "ck_shops_sales_tax_rate",
        "shops",
        "sales_tax_rate IS NULL OR (sales_tax_rate >= 0 AND sales_tax_rate <= 100)",
    )

    op.add_column("sales_records", sa.Column("item", sa.String(200), nullable=True))
    op.create_check_constraint(
        "ck_sales_records_item", "sales_records", "item IS NULL OR length(btrim(item)) > 0"
    )

    # Constant defaults fill existing rows without rewriting them (no trigger fires).
    op.add_column(
        "upload_revisions",
        sa.Column("template_format", sa.String(20), nullable=False, server_default="legacy_10col"),
    )
    op.add_column(
        "upload_revisions",
        sa.Column("tax_rate_source", sa.String(20), nullable=False, server_default="legacy_mixed"),
    )
    op.add_column(
        "upload_revisions", sa.Column("applied_sales_tax_rate", sa.Numeric(7, 4), nullable=True)
    )

    op.execute("ALTER TABLE upload_revisions DISABLE TRIGGER upload_revisions_append_only")
    op.execute(
        """
        UPDATE upload_revisions r
           SET applied_sales_tax_rate = s.rate, tax_rate_source = 'legacy_rows'
          FROM (SELECT revision_id, min(tax_percent) AS rate
                  FROM sales_records
                 GROUP BY revision_id
                HAVING count(DISTINCT tax_percent) = 1) s
         WHERE s.revision_id = r.id
        """
    )
    op.execute("ALTER TABLE upload_revisions ENABLE TRIGGER upload_revisions_append_only")

    # New revisions must state their format and tax source explicitly.
    op.alter_column("upload_revisions", "template_format", server_default=None)
    op.alter_column("upload_revisions", "tax_rate_source", server_default=None)
    op.create_check_constraint(
        "ck_upload_revisions_template_format",
        "upload_revisions",
        "template_format IN ('legacy_10col', 'standard_8col')",
    )
    op.create_check_constraint(
        "ck_upload_revisions_tax_source",
        "upload_revisions",
        "tax_rate_source IN ('shop', 'draft', 'legacy_rows', 'legacy_mixed')",
    )
    op.create_check_constraint(
        "ck_upload_revisions_tax_rate",
        "upload_revisions",
        "(applied_sales_tax_rate IS NULL) = (tax_rate_source = 'legacy_mixed') AND "
        "(applied_sales_tax_rate IS NULL OR "
        "(applied_sales_tax_rate >= 0 AND applied_sales_tax_rate <= 100)) AND "
        "(template_format = 'legacy_10col' OR tax_rate_source IN ('shop', 'draft'))",
    )


def downgrade() -> None:
    for name in (
        "ck_upload_revisions_tax_rate",
        "ck_upload_revisions_tax_source",
        "ck_upload_revisions_template_format",
    ):
        op.drop_constraint(name, "upload_revisions", type_="check")
    op.drop_column("upload_revisions", "applied_sales_tax_rate")
    op.drop_column("upload_revisions", "tax_rate_source")
    op.drop_column("upload_revisions", "template_format")
    op.drop_constraint("ck_sales_records_item", "sales_records", type_="check")
    op.drop_column("sales_records", "item")
    op.drop_constraint("ck_shops_sales_tax_rate", "shops", type_="check")
    op.drop_column("shops", "sales_tax_rate")
