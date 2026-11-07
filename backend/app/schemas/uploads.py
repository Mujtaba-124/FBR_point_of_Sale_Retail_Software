"""Excel upload API models.

Money is serialized as decimal strings (exact). CNIC/NTN is masked in every
response (last 4 characters only); the full value stays in the database and
the original file for authorized use.

Tax fields describe what was applied and saved (the revision snapshot), never
the shop's current rate. ``applied_sales_tax_rate`` is null only for a legacy
10-column revision whose rows use different rates (see each row's tax_percent).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, PlainSerializer

from app.models import SalesRecord
from app.schemas.shop_context import ShopContextOut
from app.services import excel_sales
from app.services import uploads as svc

BatchStatus = Literal["draft", "wait_for_approval", "accepted", "rejected"]
TemplateFormat = Literal["legacy_10col", "standard_8col"]
TaxSource = Literal["shop", "draft", "legacy_rows", "legacy_mixed"]

# Exact decimal strings in plain notation ("1000", never "1E+3").
Money = Annotated[Decimal, PlainSerializer(lambda d: format(d, "f"), return_type=str)]


class TotalsOut(BaseModel):
    amount: Money
    sales_tax: Money
    net_amount: Money


class UploadShopOut(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    status: Literal["active", "inactive"] = "active"


class RowErrorOut(BaseModel):
    row: int | None
    column: str | None
    code: str
    message: str


class RecordOut(BaseModel):
    excel_row: int
    sale_date: date
    sale_time: str
    item: str | None  # None only for rows of a previous 10-column revision
    customer_name: str | None
    cnic_ntn: str | None  # masked
    quantity: Money
    rate: Money
    amount: Money
    tax_percent: Money
    tax_amount: Money
    net_amount: Money

    @classmethod
    def from_parsed(cls, r: excel_sales.ParsedRow) -> "RecordOut":
        return cls(
            excel_row=r.excel_row,
            sale_date=r.sale_date,
            sale_time=r.sale_time.strftime("%H:%M:%S"),
            item=r.item,
            customer_name=r.customer_name,
            cnic_ntn=svc.mask_cnic(r.cnic_ntn),
            quantity=r.quantity,
            rate=r.rate,
            amount=r.amount,
            tax_percent=r.tax_percent,
            tax_amount=r.tax_amount,
            net_amount=r.net_amount,
        )

    @classmethod
    def from_model(cls, r: SalesRecord) -> "RecordOut":
        return cls(
            excel_row=r.excel_row,
            sale_date=r.sale_date,
            sale_time=r.sale_time.strftime("%H:%M:%S"),
            item=r.item,
            customer_name=r.customer_name,
            cnic_ntn=svc.mask_cnic(r.cnic_ntn),
            quantity=r.quantity,
            rate=r.rate,
            amount=r.amount,
            tax_percent=r.tax_percent,
            tax_amount=r.tax_amount,
            net_amount=r.net_amount,
        )


class ExistingUploadOut(BaseModel):
    id: uuid.UUID
    status: BatchStatus
    current_revision: int
    total_records: int
    can_replace: bool


class UploadPreviewOut(BaseModel):
    shop: UploadShopOut
    sales_date: date
    filename: str
    file_size: int
    checksum: str  # send back unchanged when saving
    total_rows: int
    valid_rows: int
    invalid_rows: int
    error_count: int
    errors: list[RowErrorOut]  # first 500
    errors_truncated: bool
    rounding_differences: int
    # The rate the totals were calculated with; send it back as expected_tax_rate.
    applied_sales_tax_rate: Money
    tax_rate_source: Literal["shop", "draft"]
    totals: TotalsOut  # valid rows
    rows: list[RecordOut]  # first 50 valid rows
    can_save: bool
    existing: ExistingUploadOut | None

    @classmethod
    def build(cls, p: svc.Preview, *, can_replace: bool) -> "UploadPreviewOut":
        r = p.result
        amount, tax, net = r.totals()
        existing = None
        if p.existing:
            existing = ExistingUploadOut(
                id=p.existing.id,
                status=p.existing.status,  # type: ignore[arg-type]
                current_revision=p.existing.current_revision,
                total_records=p.existing.total_records,
                can_replace=can_replace and p.existing.status == "draft",
            )
        return cls(
            shop=UploadShopOut(id=p.shop.id, name=p.shop.name, code=p.shop.code),
            sales_date=p.sales_date,
            filename=p.filename,
            file_size=p.file_size,
            checksum=p.checksum,
            total_rows=r.total_rows,
            valid_rows=r.valid_rows,
            invalid_rows=len(r.invalid_rows),
            error_count=r.error_count,
            errors=[
                RowErrorOut(row=e.row, column=e.column, code=e.code, message=e.message)
                for e in r.errors
            ],
            errors_truncated=r.error_count > len(r.errors),
            rounding_differences=r.rounding_differences,
            applied_sales_tax_rate=p.tax_rate,
            tax_rate_source=p.tax_source,  # type: ignore[arg-type]
            totals=TotalsOut(amount=amount, sales_tax=tax, net_amount=net),
            rows=[RecordOut.from_parsed(x) for x in r.rows[: svc.PREVIEW_ROWS]],
            can_save=r.ok and p.existing is None,
            existing=existing,
        )


class BatchOut(BaseModel):
    id: uuid.UUID
    shop: UploadShopOut
    sales_date: date
    filename: str
    status: BatchStatus
    current_revision: int
    total_records: int
    totals: TotalsOut
    # Of the current revision.
    template_format: TemplateFormat
    applied_sales_tax_rate: Money | None
    tax_rate_source: TaxSource
    uploaded_by: str | None
    uploaded_at: datetime
    created_at: datetime
    can_replace: bool

    @classmethod
    def build(cls, row: svc.BatchRow, *, may_replace: bool) -> "BatchOut":
        b = row.batch
        return cls(
            id=b.id,
            shop=UploadShopOut(
                id=b.shop_id,
                name=row.shop_name,
                code=row.shop_code,
                status="active" if row.shop_active else "inactive",
            ),
            sales_date=b.sales_date,
            filename=row.filename,
            status=b.status,  # type: ignore[arg-type]
            current_revision=b.current_revision,
            total_records=b.total_records,
            totals=TotalsOut(
                amount=b.total_amount, sales_tax=b.total_sales_tax, net_amount=b.total_net_amount
            ),
            template_format=row.template_format,  # type: ignore[arg-type]
            applied_sales_tax_rate=row.applied_rate,
            tax_rate_source=row.tax_source,  # type: ignore[arg-type]
            uploaded_by=row.uploaded_by,
            uploaded_at=row.uploaded_at,
            created_at=b.created_at,
            # A legacy Draft with mixed row rates has no tax basis to keep.
            can_replace=may_replace
            and b.status == "draft"
            and row.shop_active
            and row.applied_rate is not None,
        )


class BatchPageOut(BaseModel):
    items: list[BatchOut]
    total: int
    limit: int
    offset: int
    context: ShopContextOut


class RevisionOut(BaseModel):
    revision_number: int
    filename: str
    file_size: int
    checksum: str
    total_records: int
    totals: TotalsOut
    template_format: TemplateFormat
    applied_sales_tax_rate: Money | None
    tax_rate_source: TaxSource
    uploaded_by: str | None
    uploaded_at: datetime
    is_current: bool

    @classmethod
    def build(cls, r: svc.RevisionRow, current: int) -> "RevisionOut":
        v = r.revision
        return cls(
            revision_number=v.revision_number,
            filename=v.original_filename,
            file_size=v.file_size,
            checksum=v.checksum_sha256,
            total_records=v.total_records,
            totals=TotalsOut(
                amount=v.total_amount, sales_tax=v.total_sales_tax, net_amount=v.total_net_amount
            ),
            template_format=v.template_format,  # type: ignore[arg-type]
            applied_sales_tax_rate=v.applied_sales_tax_rate,
            tax_rate_source=v.tax_rate_source,  # type: ignore[arg-type]
            uploaded_by=r.uploaded_by,
            uploaded_at=v.created_at,
            is_current=v.revision_number == current,
        )


class BatchDetailOut(BaseModel):
    batch: BatchOut
    revisions: list[RevisionOut]


class RecordPageOut(BaseModel):
    items: list[RecordOut]
    total: int
    limit: int
    offset: int
    revision: int
