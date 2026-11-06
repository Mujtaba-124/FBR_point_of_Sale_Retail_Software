"""Company Workspace shop selector options.

Guards: Company account + valid subscription (router), then the shop-context
rule (``can_use_shop_context``) re-evaluated from the database on every
request. This is not Shop Management: it never needs ``shops.view`` and
returns only ID, name and code of active shops in the account's shop scope
(all, assigned only, or none).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import CompanyMember, DbSession, require_company_member
from app.schemas.shop_context import SelectionOut, ShopAccessInfoOut, ShopOptionOut, ShopOptionsOut
from app.services import shop_access
from app.services import shop_context as svc

router = APIRouter(
    prefix="/company", tags=["company"], dependencies=[Depends(require_company_member)]
)


@router.get("/shop-options", response_model=ShopOptionsOut)
def shop_options(
    user: CompanyMember,
    db: DbSession,
    selected: Annotated[str | None, Query(max_length=64)] = None,
) -> ShopOptionsOut:
    """Active shops for the selector, plus the backend's verdict on ``selected``."""
    svc.require_shop_context(db, user)
    items, total = svc.list_active_options(db, user)
    status, context = svc.selection_status(db, user, selected)
    return ShopOptionsOut(
        items=[ShopOptionOut.from_option(o) for o in items],
        total=total,
        truncated=total > len(items),
        selection=SelectionOut(
            status=status,  # type: ignore[arg-type]
            shop=ShopOptionOut.from_option(context.shop) if context.shop else None,
        ),
        access=ShopAccessInfoOut(
            mode=shop_access.summary_for(db, user).mode,  # type: ignore[arg-type]
            all_label=svc.access_label(user),
        ),
    )
