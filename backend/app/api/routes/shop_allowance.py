"""Super Admin: Shop Allowance. Aggregate settings only, no shop records.

The Super Admin guard never checks the Company subscription, so the allowance
stays manageable after expiry. PUT needs CSRF (session cookie + header).
"""

from fastapi import APIRouter

from app.api.deps import DbSession, SuperAdmin
from app.schemas.shop_allowance import (
    ShopAllowanceOut,
    ShopAllowanceUpdateOut,
    UpdateShopAllowanceRequest,
)
from app.services import shop_allowance as svc

router = APIRouter(prefix="/super-admin/shop-allowance", tags=["super-admin"])


@router.get("", response_model=ShopAllowanceOut)
def get_allowance(_: SuperAdmin, db: DbSession) -> ShopAllowanceOut:
    return ShopAllowanceOut.from_usage(svc.get_usage(db))


@router.put("", response_model=ShopAllowanceUpdateOut)
def update_allowance(
    payload: UpdateShopAllowanceRequest, user: SuperAdmin, db: DbSession
) -> ShopAllowanceUpdateOut:
    usage, changed = svc.update_allowance(
        db,
        actor=user,
        mode=payload.mode,
        max_shops=payload.max_shops,
        expected_version=payload.expected_version,
    )
    return ShopAllowanceUpdateOut(allowance=ShopAllowanceOut.from_usage(usage), changed=changed)
