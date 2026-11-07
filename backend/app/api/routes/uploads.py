"""Excel Uploads (Company Workspace).

Guards: Company account + valid subscription (router), then on every request
the module permission and the shop scope, re-read from the database:
- template / list / detail / records / original ..... uploads.view
- preview / save a new Draft ........................ uploads.upload + an active, assigned shop
- replace a Draft ................................... uploads.edit_draft + an active, assigned shop
Mutations need CSRF (session cookie + header + Origin).

The file is the raw request body (one .xlsx per request, read with a hard
size cap); shop, sales date and file name are query parameters.
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool

from app.api.deps import CompanyMember, DbSession, require_company_member
from app.core.config import get_settings
from app.core.errors import AppError, PermissionDenied
from app.schemas.shop_context import ShopContextOut
from app.schemas.uploads import (
    BatchDetailOut,
    BatchOut,
    BatchPageOut,
    RecordOut,
    RecordPageOut,
    RevisionOut,
    UploadPreviewOut,
)
from app.services import excel_sales
from app.services import uploads as svc
from app.services.permissions import has_permission

router = APIRouter(
    prefix="/company/uploads", tags=["company"], dependencies=[Depends(require_company_member)]
)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
NO_STORE = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


async def _read_file(request: Request) -> bytes:
    limit = get_settings().upload_max_bytes
    too_large = AppError(
        413, "file_too_large", f"The file is larger than {limit // (1024 * 1024)} MB."
    )
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise too_large
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise too_large
        chunks.append(chunk)
    return b"".join(chunks)


def _require_any(db: DbSession, user: CompanyMember, *keys: str) -> None:
    if not any(has_permission(db, user, k) for k in keys):
        raise PermissionDenied()


@router.get("/template")
def download_template(user: CompanyMember, db: DbSession) -> Response:
    """Blank 10-column template; no shop needed."""
    _require_any(db, user, svc.VIEW, svc.UPLOAD)
    return Response(
        content=excel_sales.build_template(),
        media_type=XLSX,
        headers={
            **NO_STORE,
            "Content-Disposition": 'attachment; filename="cheena-sales-upload-template.xlsx"',
        },
    )


@router.post("/preview", response_model=UploadPreviewOut)
async def preview_upload(
    request: Request,
    user: CompanyMember,
    db: DbSession,
    shop_id: Annotated[str | None, Query(max_length=64)] = None,
    sales_date: Annotated[str | None, Query(max_length=20)] = None,
    filename: Annotated[str | None, Query(max_length=400)] = None,
) -> UploadPreviewOut:
    """Validate a file for one shop and date. Saves nothing."""
    data = await _read_file(request)
    result = await run_in_threadpool(
        svc.preview,
        db,
        user=user,
        raw_shop_id=shop_id,
        raw_date=sales_date,
        filename=filename or "",
        data=data,
    )
    can_replace = svc.can_replace_drafts(db, user)
    return UploadPreviewOut.build(result, can_replace=can_replace)


@router.post("", response_model=BatchOut, status_code=status.HTTP_201_CREATED)
async def create_upload(
    request: Request,
    user: CompanyMember,
    db: DbSession,
    shop_id: Annotated[str | None, Query(max_length=64)] = None,
    sales_date: Annotated[str | None, Query(max_length=20)] = None,
    filename: Annotated[str | None, Query(max_length=400)] = None,
    expected_checksum: Annotated[str | None, Query(max_length=64)] = None,
    expected_tax_rate: Annotated[str | None, Query(max_length=12)] = None,
) -> BatchOut:
    """Save a validated file as a new Draft (the file is validated again here).

    ``expected_tax_rate`` is the rate the preview showed; a different current
    shop rate is refused (409 tax_rate_changed)."""
    data = await _read_file(request)
    batch = await run_in_threadpool(
        svc.create_draft,
        db,
        user=user,
        raw_shop_id=shop_id,
        raw_date=sales_date,
        filename=filename or "",
        data=data,
        expected_checksum=expected_checksum,
        expected_tax_rate=expected_tax_rate,
    )
    return BatchOut.build(
        svc.batch_row(db, user, batch.id), may_replace=svc.can_replace_drafts(db, user)
    )


@router.get("", response_model=BatchPageOut)
def list_uploads(
    user: CompanyMember,
    db: DbSession,
    shop: Annotated[str | None, Query(max_length=64)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status_filter: Annotated[str | None, Query(alias="status", max_length=24)] = None,
    sort: Annotated[
        str, Query(pattern="^(sales_date|shop|records|net|uploaded_at|status)$")
    ] = "sales_date",
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> BatchPageOut:
    if date_from and date_to and date_from > date_to:
        raise AppError(422, "invalid_date_range", "Date From must be on or before Date To.")
    rows, total, context = svc.list_batches(
        db,
        user=user,
        raw_shop_id=shop,
        date_from=date_from,
        date_to=date_to,
        status=status_filter,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )
    may_replace = svc.can_replace_drafts(db, user)
    return BatchPageOut(
        items=[BatchOut.build(r, may_replace=may_replace) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
        context=ShopContextOut.from_context(context),
    )


@router.get("/{batch_id}", response_model=BatchDetailOut)
def get_upload(batch_id: uuid.UUID, user: CompanyMember, db: DbSession) -> BatchDetailOut:
    row = svc.batch_row(db, user, batch_id)
    revisions = svc.revisions(db, user, batch_id)
    return BatchDetailOut(
        batch=BatchOut.build(row, may_replace=svc.can_replace_drafts(db, user)),
        revisions=[RevisionOut.build(r, row.batch.current_revision) for r in revisions],
    )


@router.get("/{batch_id}/records", response_model=RecordPageOut)
def list_records(
    batch_id: uuid.UUID,
    user: CompanyMember,
    db: DbSession,
    revision: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> RecordPageOut:
    rows, total, number = svc.records(
        db, user, batch_id, revision_number=revision, limit=limit, offset=offset
    )
    return RecordPageOut(
        items=[RecordOut.from_model(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
        revision=number,
    )


@router.post("/{batch_id}/replace", response_model=BatchOut)
async def replace_upload(
    batch_id: uuid.UUID,
    request: Request,
    user: CompanyMember,
    db: DbSession,
    filename: Annotated[str | None, Query(max_length=400)] = None,
    expected_checksum: Annotated[str | None, Query(max_length=64)] = None,
    expected_revision: Annotated[int | None, Query(ge=1)] = None,
    expected_tax_rate: Annotated[str | None, Query(max_length=12)] = None,
) -> BatchOut:
    """Replace a Draft with a new, fully validated file (revision n+1). The Draft's
    own tax rate is kept; ``expected_tax_rate`` must equal it."""
    data = await _read_file(request)
    await run_in_threadpool(
        svc.replace_draft,
        db,
        user=user,
        batch_id=batch_id,
        filename=filename or "",
        data=data,
        expected_checksum=expected_checksum,
        expected_revision=expected_revision,
        expected_tax_rate=expected_tax_rate,
    )
    return BatchOut.build(
        svc.batch_row(db, user, batch_id), may_replace=svc.can_replace_drafts(db, user)
    )


@router.get("/{batch_id}/revisions/{revision_number}/original")
def download_original(
    batch_id: uuid.UUID,
    revision_number: int,
    user: CompanyMember,
    db: DbSession,
) -> Response:
    """The original file of one revision (checksum-verified; audited)."""
    original = svc.download_original(db, user, batch_id, revision_number)
    name = svc.safe_download_name(original.filename)
    return Response(
        content=original.data,
        media_type=XLSX,
        headers={**NO_STORE, "Content-Disposition": f'attachment; filename="{name}"'},
    )
