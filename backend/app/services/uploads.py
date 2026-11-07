"""Excel sales uploads: preview, Draft save, controlled replacement, history.

Authorization for every operation (nothing here trusts the browser):
    Company account + valid subscription        (router guard)
  + module permission          (uploads.view / uploads.upload / uploads.edit_draft)
  + shop scope (assigned shops, or all)          (shop_context / shop_access, in SQL)
  + shop status and purpose                      (active shop for new work; history may be inactive)

Preview and save are separate requests. The save re-sends the same file and
the checksum the preview returned: a different file is refused (409), and the
file is fully re-validated, with the shop re-authorized inside the saving
transaction (row share-locked), so revocation, deactivation or expiry after
the preview are all caught. Nothing is staged on disk between the two steps.

One current upload per Shop + Sales Date (UNIQUE constraint; concurrent saves
get 409). A Draft can be replaced: the new file becomes revision n+1, the
earlier revision, its rows and its original file are kept (append-only).

Sales tax (Phase 4.2, tax exclusive). The rate a file is calculated with is:
- a new Draft: the shop's current Sales Tax % (must be configured);
- a replacement: the rate the Draft was saved with (its current revision's
  snapshot), never the shop's current rate. A Draft whose rate cannot be
  known (a legacy revision with mixed per-row rates) cannot be replaced.
The preview returns that rate; the save sends it back (``expected_tax_rate``)
and it is compared, inside the saving transaction and under the row lock
(shop FOR SHARE / batch FOR UPDATE), with the authoritative rate. A rate that
changed after the preview is refused (409) instead of saving totals the user
did not see. Every revision stores its applied rate and its source.
"""

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Select, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.core.errors import AppError, PermissionDenied
from app.models import AuditEvent, SalesRecord, Shop, UploadBatch, UploadRevision, User
from app.models.uploads import (
    BATCH_STATUSES,
    STATUS_DRAFT,
    TAX_FROM_DRAFT,
    TAX_FROM_SHOP,
    TEMPLATE_STANDARD,
)
from app.services import excel_sales, upload_storage
from app.services import shop_context as ctx
from app.services.permissions import has_permission
from app.services.subscription import business_today

logger = logging.getLogger(__name__)

VIEW, UPLOAD, REPLACE = "uploads.view", "uploads.upload", "uploads.edit_draft"
# Replacing a Draft means seeing it and uploading a newly checked file for it, so
# "Replace draft" only works together with "View" and "Upload". Holding
# uploads.edit_draft alone never opens a way around the other two.
REPLACE_REQUIRES = (VIEW, UPLOAD, REPLACE)


def can_replace_drafts(db: Session, user: User) -> bool:
    """Whether the user's role allows Draft replacement (shop scope is checked separately)."""
    return all(has_permission(db, user, key) for key in REPLACE_REQUIRES)


PREVIEW_ROWS = 50
FILENAME_MAX = 255
SORTS = ("sales_date", "shop", "records", "net", "uploaded_at", "status")


# --- Errors --------------------------------------------------------------------------------


def _not_found() -> AppError:
    return AppError(404, "upload_not_found", "Upload not found.")


def _exists() -> AppError:
    return AppError(
        409,
        "upload_exists",
        "An upload already exists for this shop and sales date. Open it and replace the Draft "
        "instead.",
    )


def _mismatch() -> AppError:
    return AppError(
        409,
        "preview_mismatch",
        "This file is not the one that was checked. Check the file again before saving.",
    )


def percent_text(rate: Decimal) -> str:
    """18.0000 -> '18', 17.50 -> '17.5' (for messages only; APIs use exact strings)."""
    text = format(rate, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _tax_not_configured() -> AppError:
    return AppError(
        409,
        "sales_tax_not_configured",
        "Sales Tax % is not configured for this shop. Configure it in Shop Management "
        "before uploading.",
    )


def _tax_changed(checked: Decimal, current: Decimal) -> AppError:
    return AppError(
        409,
        "tax_rate_changed",
        f"The Sales Tax % for this upload changed from {percent_text(checked)}% to "
        f"{percent_text(current)}% after the file was checked. Check the file again to "
        "review the new totals.",
    )


def _draft_rate_unknown() -> AppError:
    return AppError(
        409,
        "draft_tax_rate_unknown",
        "This Draft was saved with the previous template and its rows use different "
        "Sales Tax % rates, so its tax basis cannot be kept for a replacement. It stays "
        "viewable; replacing it needs a separate, reviewed tax correction.",
    )


EXPECTED_RATE_RE = re.compile(r"^\d{1,3}(\.\d{1,4})?$")


def parse_expected_rate(raw: str | None) -> Decimal:
    """The rate the preview showed, sent back by the save. Missing = no preview."""
    value = (raw or "").strip()
    if not EXPECTED_RATE_RE.match(value) or Decimal(value) > 100:
        raise AppError(
            409,
            "preview_mismatch",
            "The checked Sales Tax % is missing. Check the file again before saving.",
        )
    return Decimal(value)


def _invalid(result: excel_sales.ParseResult) -> AppError:
    return AppError(
        422,
        "upload_invalid",
        f"The file has {result.error_count} problem(s) in {len(result.invalid_rows)} row(s). "
        "Nothing was saved. Check the file to see the details.",
    )


# --- Inputs --------------------------------------------------------------------------------


def clean_filename(raw: str | None) -> str:
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(c for c in name if ord(c) >= 32 and ord(c) != 127).strip()
    if not name.lower().endswith(".xlsx") or len(name) <= len(".xlsx"):
        raise AppError(422, "not_xlsx", "Choose an Excel .xlsx file.")
    if len(name) > FILENAME_MAX:
        name = name[: FILENAME_MAX - 5].rstrip() + ".xlsx"
    return name


def parse_sales_date(raw: str | None) -> date:
    try:
        value = date.fromisoformat((raw or "").strip())
    except ValueError:
        raise AppError(422, "invalid_sales_date", "Choose a valid sales date.") from None
    if value > business_today():
        raise AppError(422, "invalid_sales_date", "The sales date cannot be in the future.")
    return value


def mask_cnic(value: str | None) -> str | None:
    """Show only the last 4 characters; keep hyphens for readability."""
    if not value:
        return value
    keep = 4
    out, seen = [], 0
    for ch in reversed(value):
        if ch == "-":
            out.append(ch)
        elif seen < keep:
            out.append(ch)
            seen += 1
        else:
            out.append("•")
    return "".join(reversed(out))


# --- Preview ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class ExistingBatch:
    id: uuid.UUID
    status: str
    current_revision: int
    total_records: int
    applied_rate: Decimal | None  # the current revision's tax snapshot (None: mixed legacy)


@dataclass(frozen=True)
class Preview:
    shop: ctx.ShopOption
    sales_date: date
    filename: str
    file_size: int
    checksum: str
    result: excel_sales.ParseResult
    existing: ExistingBatch | None
    tax_rate: Decimal
    tax_source: str  # "shop" (new Draft) or "draft" (kept from the existing Draft)


def _existing(db: Session, shop_id: uuid.UUID, sales_date: date) -> ExistingBatch | None:
    row = db.execute(
        select(
            UploadBatch.id,
            UploadBatch.status,
            UploadBatch.current_revision,
            UploadBatch.total_records,
            UploadRevision.applied_sales_tax_rate,
        )
        .join(
            UploadRevision,
            (UploadRevision.batch_id == UploadBatch.id)
            & (UploadRevision.revision_number == UploadBatch.current_revision),
        )
        .where(UploadBatch.shop_id == shop_id, UploadBatch.sales_date == sales_date)
    ).one_or_none()
    return ExistingBatch(*row) if row else None


def _shop_rate(db: Session, shop_id: uuid.UUID) -> Decimal:
    """The shop's configured Sales Tax % (read in the caller's transaction)."""
    rate = db.scalar(select(Shop.sales_tax_rate).where(Shop.id == shop_id))
    if rate is None:
        raise _tax_not_configured()
    return rate


def _draft_rate(db: Session, batch: UploadBatch) -> Decimal:
    """The tax snapshot a Draft was saved with (its current revision)."""
    rate = db.scalar(
        select(UploadRevision.applied_sales_tax_rate).where(
            UploadRevision.batch_id == batch.id,
            UploadRevision.revision_number == batch.current_revision,
        )
    )
    if rate is None:
        raise _draft_rate_unknown()
    return rate


def preview(
    db: Session,
    *,
    user: User,
    raw_shop_id: str | None,
    raw_date: str | None,
    filename: str,
    data: bytes,
) -> Preview:
    """Validate without saving anything."""
    name = clean_filename(filename)
    sales_date = parse_sales_date(raw_date)
    context = ctx.resolve_operational_shop(db, user, raw_shop_id, permission=UPLOAD)
    assert context.shop is not None
    existing = _existing(db, context.shop.id, sales_date)
    if existing is not None:
        # Saving can only replace this Draft, which keeps its own rate.
        if existing.applied_rate is None:
            db.rollback()
            raise _draft_rate_unknown()
        tax_rate, tax_source = existing.applied_rate, TAX_FROM_DRAFT
    else:
        try:
            tax_rate, tax_source = _shop_rate(db, context.shop.id), TAX_FROM_SHOP
        finally:
            db.rollback()
    db.rollback()  # release the shop share-lock; nothing to keep
    result = excel_sales.parse_workbook(data, sales_date, tax_rate)
    return Preview(
        shop=context.shop,
        sales_date=sales_date,
        filename=name,
        file_size=len(data),
        checksum=upload_storage.checksum(data),
        result=result,
        existing=existing,
        tax_rate=tax_rate,
        tax_source=tax_source,
    )


# --- Saving -----------------------------------------------------------------------------------


def _audit(db: Session, user: User, action: str, details: dict[str, object]) -> None:
    db.add(AuditEvent(action=action, actor=f"user:{user.id}", details=details))


def _record_rejection(
    db: Session, user: User, shop_id: str | None, result: excel_sales.ParseResult
) -> None:
    """Counts only: never file contents or customer data."""
    try:
        _audit(
            db,
            user,
            "upload.rejected",
            {
                "shop_id": shop_id,
                "rows": result.total_rows,
                "invalid_rows": len(result.invalid_rows),
                "errors": result.error_count,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("could not audit an upload rejection")


def _validated(
    db: Session,
    user: User,
    data: bytes,
    sales_date: date,
    expected_checksum: str | None,
    shop_ref: str | None,
    tax_rate: Decimal,
) -> excel_sales.ParseResult:
    if not expected_checksum or upload_storage.checksum(data) != expected_checksum.strip().lower():
        raise _mismatch()
    result = excel_sales.parse_workbook(data, sales_date, tax_rate)
    if not result.ok:
        _record_rejection(db, user, shop_ref, result)
        raise _invalid(result)
    return result


def _insert_revision(
    db: Session,
    *,
    batch: UploadBatch,
    number: int,
    user: User,
    filename: str,
    stored: upload_storage.StoredFile,
    result: excel_sales.ParseResult,
    tax_rate: Decimal,
    tax_source: str,
) -> UploadRevision:
    amount, tax, net = result.totals()
    revision = UploadRevision(
        batch_id=batch.id,
        revision_number=number,
        original_filename=filename,
        storage_key=stored.key,
        checksum_sha256=stored.checksum_sha256,
        file_size=stored.size,
        total_records=len(result.rows),
        total_amount=amount,
        total_sales_tax=tax,
        total_net_amount=net,
        template_format=TEMPLATE_STANDARD,
        applied_sales_tax_rate=tax_rate,
        tax_rate_source=tax_source,
        uploaded_by_user_id=user.id,
    )
    db.add(revision)
    db.flush()
    db.execute(
        insert(SalesRecord),
        [
            {
                "revision_id": revision.id,
                "batch_id": batch.id,
                "shop_id": batch.shop_id,
                "excel_row": r.excel_row,
                "sale_date": r.sale_date,
                "sale_time": r.sale_time,
                "item": r.item,
                "customer_name": r.customer_name,
                "cnic_ntn": r.cnic_ntn,
                "quantity": r.quantity,
                "rate": r.rate,
                "amount": r.amount,
                "tax_percent": r.tax_percent,
                "tax_amount": r.tax_amount,
                "net_amount": r.net_amount,
            }
            for r in result.rows
        ],
    )
    batch.current_revision = number
    batch.total_records = revision.total_records
    batch.total_amount = amount
    batch.total_sales_tax = tax
    batch.total_net_amount = net
    batch.updated_by_user_id = user.id
    return revision


def create_draft(
    db: Session,
    *,
    user: User,
    raw_shop_id: str | None,
    raw_date: str | None,
    filename: str,
    data: bytes,
    expected_checksum: str | None,
    expected_tax_rate: str | None,
) -> UploadBatch:
    name = clean_filename(filename)
    sales_date = parse_sales_date(raw_date)
    checked_rate = parse_expected_rate(expected_tax_rate)
    # Authorize before spending effort (and again inside the transaction below).
    ctx.resolve_operational_shop(db, user, raw_shop_id, permission=UPLOAD)
    db.rollback()
    result = _validated(db, user, data, sales_date, expected_checksum, raw_shop_id, checked_rate)
    stored = upload_storage.save(data)
    try:
        # Shop row FOR SHARE until commit: a Sales Tax % edit (FOR UPDATE) waits for us,
        # or we see its committed rate here.
        context = ctx.resolve_operational_shop(db, user, raw_shop_id, permission=UPLOAD)
        assert context.shop is not None
        existing = _existing(db, context.shop.id, sales_date)
        if existing is not None:
            raise _exists()
        shop_rate = _shop_rate(db, context.shop.id)
        if shop_rate != checked_rate:
            raise _tax_changed(checked_rate, shop_rate)
        amount, tax, net = result.totals()
        batch = UploadBatch(
            shop_id=context.shop.id,
            sales_date=sales_date,
            status=STATUS_DRAFT,
            current_revision=1,
            total_records=len(result.rows),
            total_amount=amount,
            total_sales_tax=tax,
            total_net_amount=net,
            created_by_user_id=user.id,
            updated_by_user_id=user.id,
        )
        db.add(batch)
        db.flush()
        _insert_revision(
            db,
            batch=batch,
            number=1,
            user=user,
            filename=name,
            stored=stored,
            result=result,
            tax_rate=shop_rate,
            tax_source=TAX_FROM_SHOP,
        )
        _audit(
            db,
            user,
            "upload.created",
            {
                "batch_id": str(batch.id),
                "shop_id": str(batch.shop_id),
                "sales_date": sales_date.isoformat(),
                "revision": 1,
                "records": len(result.rows),
                "file_size": stored.size,
                "checksum": stored.checksum_sha256,
                "template_format": TEMPLATE_STANDARD,
                "applied_sales_tax_rate": format(shop_rate, "f"),
                "tax_rate_source": TAX_FROM_SHOP,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        upload_storage.discard(stored.key)
        if "uq_upload_batches_shop_date" in str(exc.orig):
            raise _exists() from None
        raise
    except Exception:
        db.rollback()
        upload_storage.discard(stored.key)
        raise
    logger.info("upload created by %s", user.id, extra={"batch_id": str(batch.id)})
    return batch


def replace_draft(
    db: Session,
    *,
    user: User,
    batch_id: uuid.UUID,
    filename: str,
    data: bytes,
    expected_checksum: str | None,
    expected_revision: int | None,
    expected_tax_rate: str | None,
) -> UploadBatch:
    """Add revision n+1 to a Draft, keeping the Draft's tax rate. A failed attempt
    leaves the current Draft untouched."""
    if not can_replace_drafts(db, user):
        raise PermissionDenied()
    name = clean_filename(filename)
    checked_rate = parse_expected_rate(expected_tax_rate)
    batch = visible_batch(db, user, batch_id, permission=REPLACE)
    shop_ref, sales_date = str(batch.shop_id), batch.sales_date
    ctx.resolve_operational_shop(db, user, shop_ref, permission=REPLACE)
    db.rollback()
    result = _validated(db, user, data, sales_date, expected_checksum, shop_ref, checked_rate)
    stored = upload_storage.save(data)
    try:
        ctx.resolve_operational_shop(db, user, shop_ref, permission=REPLACE)
        locked = db.scalar(select(UploadBatch).where(UploadBatch.id == batch_id).with_for_update())
        if locked is None:
            raise _not_found()
        if locked.status != STATUS_DRAFT:
            raise AppError(
                409,
                "upload_not_draft",
                "Only a Draft can be replaced. This upload has already moved on in the workflow.",
            )
        if expected_revision is None or locked.current_revision != expected_revision:
            raise AppError(
                409,
                "stale_upload",
                "This upload was changed after you opened it. Reload it and try again.",
            )
        draft_rate = _draft_rate(db, locked)
        if draft_rate != checked_rate:
            raise _tax_changed(checked_rate, draft_rate)
        previous = locked.current_revision
        _insert_revision(
            db,
            batch=locked,
            number=previous + 1,
            user=user,
            filename=name,
            stored=stored,
            result=result,
            tax_rate=draft_rate,
            tax_source=TAX_FROM_DRAFT,
        )
        _audit(
            db,
            user,
            "upload.replaced",
            {
                "batch_id": str(locked.id),
                "shop_id": str(locked.shop_id),
                "sales_date": sales_date.isoformat(),
                "previous_revision": previous,
                "revision": previous + 1,
                "records": len(result.rows),
                "checksum": stored.checksum_sha256,
                "template_format": TEMPLATE_STANDARD,
                "applied_sales_tax_rate": format(draft_rate, "f"),
                "tax_rate_source": TAX_FROM_DRAFT,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        upload_storage.discard(stored.key)
        raise
    return locked


# --- Reading ------------------------------------------------------------------------------------


def visible_batch(
    db: Session, user: User, batch_id: uuid.UUID, *, permission: str = VIEW
) -> UploadBatch:
    """The batch, if its shop is in the user's scope (inactive shops included: history)."""
    ctx.require_module(db, user, permission)
    batch = db.scalar(
        select(UploadBatch).where(
            UploadBatch.id == batch_id, ctx.scope_filter(user, ctx.ALL_SHOPS, UploadBatch.shop_id)
        )
    )
    if batch is None:
        raise _not_found()
    return batch


@dataclass(frozen=True)
class BatchRow:
    batch: UploadBatch
    shop_name: str
    shop_code: str
    shop_active: bool
    filename: str
    uploaded_by: str | None
    uploaded_at: datetime
    template_format: str
    applied_rate: Decimal | None
    tax_source: str


def _batch_rows_query() -> Select:  # type: ignore[type-arg]
    revision = aliased(UploadRevision)
    uploader = aliased(User)
    return (
        select(
            UploadBatch,
            Shop.name,
            Shop.code,
            Shop.is_active,
            revision.original_filename,
            uploader.full_name,
            revision.created_at,
            revision.template_format,
            revision.applied_sales_tax_rate,
            revision.tax_rate_source,
        )
        .join(Shop, Shop.id == UploadBatch.shop_id)
        .join(
            revision,
            (revision.batch_id == UploadBatch.id)
            & (revision.revision_number == UploadBatch.current_revision),
        )
        .outerjoin(uploader, uploader.id == revision.uploaded_by_user_id)
    )


def list_batches(
    db: Session,
    *,
    user: User,
    raw_shop_id: str | None,
    date_from: date | None,
    date_to: date | None,
    status: str | None,
    sort: str,
    order: str,
    limit: int,
    offset: int,
) -> tuple[list[BatchRow], int, ctx.ShopContext]:
    """Filtered in SQL to the user's shop scope (All Shops / All Assigned Shops / one shop)."""
    context = ctx.resolve(db, user, raw_shop_id, purpose=ctx.Purpose.HISTORY, permission=VIEW)
    stmt = _batch_rows_query().where(ctx.scope_filter(user, context, UploadBatch.shop_id))
    if date_from:
        stmt = stmt.where(UploadBatch.sales_date >= date_from)
    if date_to:
        stmt = stmt.where(UploadBatch.sales_date <= date_to)
    if status:
        if status not in BATCH_STATUSES:
            raise AppError(422, "invalid_status", "Unknown status.")
        stmt = stmt.where(UploadBatch.status == status)
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    column = {
        "sales_date": UploadBatch.sales_date,
        "shop": func.lower(Shop.name),
        "records": UploadBatch.total_records,
        "net": UploadBatch.total_net_amount,
        "uploaded_at": UploadBatch.updated_at,
        "status": UploadBatch.status,
    }[sort]
    ordered = column.desc() if order == "desc" else column.asc()
    rows = db.execute(stmt.order_by(ordered, UploadBatch.id).limit(limit).offset(offset)).all()
    return [BatchRow(*r) for r in rows], total, context


def batch_row(db: Session, user: User, batch_id: uuid.UUID) -> BatchRow:
    visible_batch(db, user, batch_id)
    row = db.execute(_batch_rows_query().where(UploadBatch.id == batch_id)).one()
    return BatchRow(*row)


@dataclass(frozen=True)
class RevisionRow:
    revision: UploadRevision
    uploaded_by: str | None


def revisions(db: Session, user: User, batch_id: uuid.UUID) -> list[RevisionRow]:
    visible_batch(db, user, batch_id)
    rows = db.execute(
        select(UploadRevision, User.full_name)
        .outerjoin(User, User.id == UploadRevision.uploaded_by_user_id)
        .where(UploadRevision.batch_id == batch_id)
        .order_by(UploadRevision.revision_number.desc())
    ).all()
    return [RevisionRow(r, n) for r, n in rows]


def records(
    db: Session,
    user: User,
    batch_id: uuid.UUID,
    *,
    revision_number: int | None,
    limit: int,
    offset: int,
) -> tuple[list[SalesRecord], int, int]:
    """Rows of one revision (the current one by default). Returns (rows, total, revision)."""
    batch = visible_batch(db, user, batch_id)
    number = revision_number or batch.current_revision
    revision_id = db.scalar(
        select(UploadRevision.id).where(
            UploadRevision.batch_id == batch.id, UploadRevision.revision_number == number
        )
    )
    if revision_id is None:
        raise _not_found()
    total = int(
        db.scalar(
            select(func.count())
            .select_from(SalesRecord)
            .where(SalesRecord.revision_id == revision_id)
        )
        or 0
    )
    rows = db.scalars(
        select(SalesRecord)
        .where(SalesRecord.revision_id == revision_id)
        .order_by(SalesRecord.excel_row)
        .limit(limit)
        .offset(offset)
    ).all()
    return list(rows), total, number


@dataclass(frozen=True)
class OriginalFile:
    data: bytes
    filename: str


def download_original(
    db: Session, user: User, batch_id: uuid.UUID, revision_number: int
) -> OriginalFile:
    batch = visible_batch(db, user, batch_id)
    revision = db.scalar(
        select(UploadRevision).where(
            UploadRevision.batch_id == batch.id, UploadRevision.revision_number == revision_number
        )
    )
    if revision is None:
        raise _not_found()
    data = upload_storage.read(revision.storage_key, revision.checksum_sha256)
    _audit(
        db,
        user,
        "upload.original_downloaded",
        {"batch_id": str(batch.id), "revision": revision_number, "shop_id": str(batch.shop_id)},
    )
    db.commit()
    return OriginalFile(data=data, filename=revision.original_filename)


def safe_download_name(filename: str) -> str:
    """ASCII-only, quote-free name for Content-Disposition."""
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "_", filename).strip() or "upload.xlsx"
    return cleaned if cleaned.lower().endswith(".xlsx") else cleaned + ".xlsx"


# --- Dashboard aggregates ------------------------------------------------------------------------


@dataclass(frozen=True)
class SalesSummary:
    uploads: int
    records: int
    amount: Decimal
    tax: Decimal
    net: Decimal


def sales_summary(db: Session, user: User, context: ctx.ShopContext) -> SalesSummary:
    row = db.execute(
        select(
            func.count(UploadBatch.id),
            func.coalesce(func.sum(UploadBatch.total_records), 0),
            func.coalesce(func.sum(UploadBatch.total_amount), 0),
            func.coalesce(func.sum(UploadBatch.total_sales_tax), 0),
            func.coalesce(func.sum(UploadBatch.total_net_amount), 0),
        ).where(ctx.scope_filter(user, context, UploadBatch.shop_id))
    ).one()
    return SalesSummary(int(row[0]), int(row[1]), Decimal(row[2]), Decimal(row[3]), Decimal(row[4]))


def recent_batches(
    db: Session, user: User, context: ctx.ShopContext, limit: int = 5
) -> list[BatchRow]:
    rows = db.execute(
        _batch_rows_query()
        .where(ctx.scope_filter(user, context, UploadBatch.shop_id))
        .order_by(UploadBatch.updated_at.desc(), UploadBatch.id)
        .limit(limit)
    ).all()
    return [BatchRow(*r) for r in rows]
