"""Excel sales uploads: batches, immutable revisions and their sales records.

- ``upload_batches``: the one *current* upload for a Shop + Sales Date
  (UNIQUE (shop_id, sales_date)). Holds the status and points at its current
  revision by number. Totals are copied from that revision for fast listing.
- ``upload_revisions``: every accepted file, append-only (a trigger in
  migration 0011 refuses UPDATE and DELETE). A Draft replacement adds revision
  n+1; earlier revisions, their original files and rows stay for audit.
- ``sales_records``: the validated rows of one revision, append-only as well.
  Uploaded values are stored exactly as validated, never recalculated.

Money uses NUMERIC (never float). The approval workflow (Wait for Approval,
Accept, Reject) is a later module; only ``draft`` is created here.

Tax (Phase 4.2, tax exclusive): each revision stores the Sales Tax % it was
calculated with (``applied_sales_tax_rate``) and where it came from: ``shop``
(the shop's rate when the Draft was first saved), ``draft`` (kept from the
Draft being replaced), ``legacy_rows`` (one uniform rate found in a previous
10-column revision) or ``legacy_mixed`` (rows with different rates; NULL,
the per-row ``tax_percent`` stays authoritative). Nothing is ever recalculated
from a shop's current rate.
"""

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

STATUS_DRAFT = "draft"
STATUS_WAIT_FOR_APPROVAL = "wait_for_approval"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"
BATCH_STATUSES = (STATUS_DRAFT, STATUS_WAIT_FOR_APPROVAL, STATUS_ACCEPTED, STATUS_REJECTED)

TEMPLATE_LEGACY = "legacy_10col"  # Date..Amount, Sale Tax %, Sale Tax Amount, Net Amount
TEMPLATE_STANDARD = "standard_8col"  # Date, Time, Item, Customer, CNIC/NTN, Qty, Rate, Amount
TAX_FROM_SHOP, TAX_FROM_DRAFT = "shop", "draft"
TAX_LEGACY_ROWS, TAX_LEGACY_MIXED = "legacy_rows", "legacy_mixed"

MONEY = Numeric(14, 2)
QUANTITY = Numeric(14, 3)
RATE = Numeric(16, 4)
PERCENT = Numeric(7, 4)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


class UploadBatch(Base):
    __tablename__ = "upload_batches"
    __table_args__ = (
        UniqueConstraint("shop_id", "sales_date", name="uq_upload_batches_shop_date"),
        CheckConstraint(
            "status IN ('draft', 'wait_for_approval', 'accepted', 'rejected')",
            name="ck_upload_batches_status",
        ),
        CheckConstraint("current_revision >= 1", name="ck_upload_batches_revision"),
        CheckConstraint("total_records >= 1", name="ck_upload_batches_records"),
        Index("ix_upload_batches_sales_date", "sales_date"),
        Index("ix_upload_batches_status", "status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="RESTRICT"), nullable=False
    )
    sales_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="draft")
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    total_records: Mapped[int] = mapped_column(Integer, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    total_sales_tax: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    total_net_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class UploadRevision(Base):
    __tablename__ = "upload_revisions"
    __table_args__ = (
        UniqueConstraint("batch_id", "revision_number", name="uq_upload_revisions_number"),
        UniqueConstraint("storage_key", name="uq_upload_revisions_storage_key"),
        CheckConstraint("revision_number >= 1", name="ck_upload_revisions_number"),
        CheckConstraint("file_size > 0", name="ck_upload_revisions_size"),
        CheckConstraint("total_records >= 1", name="ck_upload_revisions_records"),
        CheckConstraint("checksum_sha256 ~ '^[0-9a-f]{64}$'", name="ck_upload_revisions_checksum"),
        CheckConstraint(
            "template_format IN ('legacy_10col', 'standard_8col')",
            name="ck_upload_revisions_template_format",
        ),
        CheckConstraint(
            "tax_rate_source IN ('shop', 'draft', 'legacy_rows', 'legacy_mixed')",
            name="ck_upload_revisions_tax_source",
        ),
        CheckConstraint(
            "(applied_sales_tax_rate IS NULL) = (tax_rate_source = 'legacy_mixed') AND "
            "(applied_sales_tax_rate IS NULL OR "
            "(applied_sales_tax_rate >= 0 AND applied_sales_tax_rate <= 100)) AND "
            "(template_format = 'legacy_10col' OR tax_rate_source IN ('shop', 'draft'))",
            name="ck_upload_revisions_tax_rate",
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("upload_batches.id", ondelete="RESTRICT"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(200), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    total_records: Mapped[int] = mapped_column(Integer, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    total_sales_tax: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    total_net_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    template_format: Mapped[str] = mapped_column(String(20), nullable=False)
    applied_sales_tax_rate: Mapped[Decimal | None] = mapped_column(PERCENT)
    tax_rate_source: Mapped[str] = mapped_column(String(20), nullable=False)
    # RESTRICT (migration 0012): revisions are immutable, so the uploader is kept.
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SalesRecord(Base):
    __tablename__ = "sales_records"
    __table_args__ = (
        UniqueConstraint("revision_id", "excel_row", name="uq_sales_records_revision_row"),
        Index("ix_sales_records_shop_date", "shop_id", "sale_date"),
        CheckConstraint("quantity > 0", name="ck_sales_records_quantity"),
        CheckConstraint("rate >= 0", name="ck_sales_records_rate"),
        CheckConstraint("amount >= 0", name="ck_sales_records_amount"),
        CheckConstraint("tax_percent >= 0 AND tax_percent <= 100", name="ck_sales_records_tax_pct"),
        CheckConstraint("tax_amount >= 0", name="ck_sales_records_tax"),
        CheckConstraint("net_amount >= 0", name="ck_sales_records_net"),
        CheckConstraint("item IS NULL OR length(btrim(item)) > 0", name="ck_sales_records_item"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("upload_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("upload_batches.id", ondelete="RESTRICT"), nullable=False
    )
    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="RESTRICT"), nullable=False
    )
    excel_row: Mapped[int] = mapped_column(Integer, nullable=False)
    sale_date: Mapped[date] = mapped_column(Date, nullable=False)
    sale_time: Mapped[time] = mapped_column(Time, nullable=False)
    item: Mapped[str | None] = mapped_column(String(200))  # NULL only for 10-column rows
    customer_name: Mapped[str | None] = mapped_column(Text)
    cnic_ntn: Mapped[str | None] = mapped_column(String(20))
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    rate: Mapped[Decimal] = mapped_column(RATE, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    tax_percent: Mapped[Decimal] = mapped_column(PERCENT, nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
