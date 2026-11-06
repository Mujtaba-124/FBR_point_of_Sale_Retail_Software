"""Shop Management (Company Workspace).

Every route: Company account + valid subscription (router guard), then the
specific capability, re-read from the database on each request:
- list / details ............ shops.view
- create .................... shops.create (+ shops.manage_integration if a token is sent)
- edit profile fields ....... shops.edit
- deactivate / reactivate ... shops.delete  (there is no permanent deletion)
- set / replace FBR token ... shops.manage_integration
- allowance (read only) ..... shops.view  (only the Super Admin can change it)
Company Admin holds all of them; the Super Admin none. Mutations need CSRF.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession, require_company_member, require_company_permission
from app.core.errors import PermissionDenied
from app.models import User
from app.schemas.shop_allowance import AllowanceSummaryOut
from app.schemas.shops import (
    CreateShopRequest,
    SetFbrTokenRequest,
    ShopOut,
    ShopPageOut,
    ShopSummaryOut,
    ShopVersionRequest,
    UpdateShopRequest,
)
from app.services import shop_allowance
from app.services import shops as svc
from app.services.permissions import has_permission

router = APIRouter(
    prefix="/company/shops", tags=["company"], dependencies=[Depends(require_company_member)]
)

ShopViewer = Annotated[User, Depends(require_company_permission("shops.view"))]
ShopCreator = Annotated[User, Depends(require_company_permission("shops.create"))]
ShopEditor = Annotated[User, Depends(require_company_permission("shops.edit"))]
ShopActivator = Annotated[User, Depends(require_company_permission("shops.delete"))]
CompanyMemberUser = Annotated[User, Depends(require_company_member)]

TOKEN_PERMISSION = "shops.manage_integration"


def _require_token_permission(db: DbSession, user: User, shop_id: uuid.UUID | None) -> None:
    if not has_permission(db, user, TOKEN_PERMISSION):
        svc.record_token_denial(db, user, shop_id)
        raise PermissionDenied("You do not have permission to manage FBR tokens.")


@router.get("", response_model=ShopPageOut)
def list_shops(
    _: ShopViewer,
    db: DbSession,
    search: Annotated[str | None, Query(max_length=100)] = None,
    status_filter: Annotated[
        str | None, Query(alias="status", pattern="^(active|inactive)$")
    ] = None,
    sort: Annotated[str, Query(pattern="^(name|code|branch|pos_id|status|created)$")] = "name",
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> ShopPageOut:
    rows, total = svc.list_shops(
        db, search=search, status=status_filter, sort=sort, order=order, limit=limit, offset=offset
    )
    return ShopPageOut(
        items=[ShopOut.from_model(s) for s in rows],
        total=total,
        limit=limit,
        offset=offset,
        summary=ShopSummaryOut.from_counts(svc.counts(db)),
        allowance=AllowanceSummaryOut.from_usage(shop_allowance.get_usage(db)),
    )


@router.get("/allowance", response_model=AllowanceSummaryOut)
def get_allowance(_: ShopViewer, db: DbSession) -> AllowanceSummaryOut:
    """Read-only aggregate. Declared before ``/{shop_id}`` so it is matched first."""
    return AllowanceSummaryOut.from_usage(shop_allowance.get_usage(db))


@router.post("", response_model=ShopOut, status_code=status.HTTP_201_CREATED)
def create_shop(payload: CreateShopRequest, user: ShopCreator, db: DbSession) -> ShopOut:
    token = payload.fbr_token if payload.fbr_token and payload.fbr_token.strip() else None
    if token is not None:
        _require_token_permission(db, user, None)
    shop = svc.create_shop(
        db,
        actor=user,
        name=payload.name,
        branch_name=payload.branch_name,
        code=payload.code,
        pos_id=payload.pos_id,
        fbr_token=token,
    )
    return ShopOut.from_model(shop)


@router.get("/{shop_id}", response_model=ShopOut)
def get_shop(shop_id: uuid.UUID, _: ShopViewer, db: DbSession) -> ShopOut:
    return ShopOut.from_model(svc.get_shop(db, shop_id))


@router.patch("/{shop_id}", response_model=ShopOut)
def update_shop(
    shop_id: uuid.UUID, payload: UpdateShopRequest, user: ShopEditor, db: DbSession
) -> ShopOut:
    shop = svc.update_shop(
        db,
        actor=user,
        shop_id=shop_id,
        expected_version=payload.expected_version,
        name=payload.name,
        branch_name=payload.branch_name,
        code=payload.code,
        pos_id=payload.pos_id,
    )
    return ShopOut.from_model(shop)


@router.post("/{shop_id}/deactivate", response_model=ShopOut)
def deactivate_shop(
    shop_id: uuid.UUID, payload: ShopVersionRequest, user: ShopActivator, db: DbSession
) -> ShopOut:
    shop = svc.set_active(
        db, actor=user, shop_id=shop_id, expected_version=payload.expected_version, active=False
    )
    return ShopOut.from_model(shop)


@router.post("/{shop_id}/reactivate", response_model=ShopOut)
def reactivate_shop(
    shop_id: uuid.UUID, payload: ShopVersionRequest, user: ShopActivator, db: DbSession
) -> ShopOut:
    shop = svc.set_active(
        db, actor=user, shop_id=shop_id, expected_version=payload.expected_version, active=True
    )
    return ShopOut.from_model(shop)


@router.put("/{shop_id}/fbr-token", response_model=ShopOut)
def set_fbr_token(
    shop_id: uuid.UUID, payload: SetFbrTokenRequest, user: CompanyMemberUser, db: DbSession
) -> ShopOut:
    _require_token_permission(db, user, shop_id)
    shop = svc.set_fbr_token(
        db,
        actor=user,
        shop_id=shop_id,
        expected_version=payload.expected_version,
        token=payload.fbr_token,
    )
    return ShopOut.from_model(shop)
