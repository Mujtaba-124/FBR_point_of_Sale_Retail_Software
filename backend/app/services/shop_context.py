"""Company Workspace shop context: "All Shops" or one specific shop.

The selected shop is a CONTEXT / FILTER, never a permission. Module access is
still decided by the role permissions on every request; selecting a shop
cannot grant anything.

Who may use a shop context
    Only accounts that can use at least one *implemented* shop-aware module
    (``CONSUMERS``). Today that is the Company Dashboard summary, which is
    Company Admin only, so Company Users have no shop context yet. When Excel
    Uploads, Approvals, FBR Sync or Reports are built, flip ``implemented``
    for that consumer and holders of its view permission gain the selector.

Which shops
    ``shop_access_condition`` delegates to ``app.services.shop_access``: the
    Company Admin sees every shop; a Company User sees all shops, only the
    assigned ones, or none, per their shop access (Phase 3.3). The condition is
    SQL evaluated in the caller's query, so every consumer inherits the rule
    and a revocation applies on the next request.

Future modules
    - one active shop for a new upload / FBR submission:
        ``resolve_operational_shop(db, user, raw_id, permission="uploads.upload")``
    - consolidated reads (All Shops / All Assigned Shops), filtered in SQL:
        ``stmt.where(scope_filter(user, context, Sales.shop_id))``
    - one historical shop, inactive allowed:
        ``resolve_historical_shop(db, user, raw_id, permission="reports.view")``

Resolution (``resolve``)
    The backend never trusts a shop ID from the browser:
    - absent / "all"              -> All Shops (unless the caller requires one shop)
    - not a UUID                  -> 422 invalid_shop_id
    - unknown or not accessible   -> 404 shop_not_found (no existence leak)
    - inactive, for READ/OPERATE  -> 409 shop_inactive
    - inactive, for HISTORY       -> allowed (explicit read-only historical mode)
    OPERATE also takes a FOR SHARE lock on the shop row, so a concurrent
    deactivation waits until the operational write commits.
Always the immutable shop ID; never the display name or the editable code.
"""

import uuid
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, PermissionDenied
from app.models import AccessCategory, Shop, User
from app.services import shop_access
from app.services.permissions import has_permission

MAX_OPTIONS = 5_000
COMPANY_CATEGORIES = (AccessCategory.COMPANY_ADMIN, AccessCategory.COMPANY_USER)


class Purpose(StrEnum):
    READ = "read"  # current views (dashboard, future lists): active shops only
    OPERATE = "operate"  # new operational work (uploads, FBR submissions): active only
    HISTORY = "history"  # future read-only historical reporting: inactive allowed


@dataclass(frozen=True)
class Consumer:
    """A module that reads the shop context."""

    key: str
    implemented: bool
    permission: str | None = None  # None: Company Admin only
    requires_single_shop: bool = False  # e.g. Excel Upload never runs for All Shops


CONSUMERS: tuple[Consumer, ...] = (
    Consumer("dashboard_analytics", implemented=True),  # /company/dashboard/summary
    Consumer("uploads", implemented=False, permission="uploads.view", requires_single_shop=True),
    Consumer("approvals", implemented=False, permission="approvals.view"),
    Consumer("fbr_sync", implemented=False, permission="fbr_sync.view"),
    Consumer("reports", implemented=False, permission="reports.view"),
)


@dataclass(frozen=True)
class ShopOption:
    id: uuid.UUID
    name: str
    code: str


@dataclass(frozen=True)
class ShopContext:
    """``shop`` is None for All Shops."""

    shop: ShopOption | None
    is_active: bool = True

    @property
    def scope(self) -> str:
        return "all" if self.shop is None else "shop"

    @property
    def shop_id(self) -> uuid.UUID | None:
        return self.shop.id if self.shop else None


ALL_SHOPS = ShopContext(shop=None)


# --- Errors -------------------------------------------------------------------------


def _invalid_id() -> AppError:
    return AppError(422, "invalid_shop_id", "The selected shop is not valid.")


def _not_found() -> AppError:
    return AppError(404, "shop_not_found", "The selected shop is no longer available.")


def _inactive() -> AppError:
    return AppError(
        409,
        "shop_inactive",
        "The selected shop is no longer active. Choose an active shop or All Shops.",
    )


def _shop_required() -> AppError:
    return AppError(422, "shop_required", "Choose one active shop. All Shops cannot be used here.")


# --- Authorization -------------------------------------------------------------------


def _consumer_allows(db: Session, user: User, consumer: Consumer) -> bool:
    if not consumer.implemented:
        return False
    if consumer.permission is None:
        return user.access_category == AccessCategory.COMPANY_ADMIN
    return has_permission(db, user, consumer.permission)


def can_use_shop_context(db: Session, user: User) -> bool:
    """Deny by default: active Company accounts with an implemented shop-aware module."""
    if not user.is_active or user.access_category not in COMPANY_CATEGORIES:
        return False
    return any(_consumer_allows(db, user, c) for c in CONSUMERS)


def require_shop_context(db: Session, user: User) -> None:
    if not can_use_shop_context(db, user):
        raise PermissionDenied("Your account does not use a shop context.")


def shop_access_condition(user: User) -> ColumnElement[bool]:
    """SQL condition limiting the shops ``user`` may see in any shop context."""
    return shop_access.scope_condition(user)


def require_module(db: Session, user: User, permission: str | None) -> None:
    """No permission given: any implemented shop-aware module. Otherwise that one."""
    if permission is None:
        require_shop_context(db, user)
    elif not (
        user.is_active
        and user.access_category in COMPANY_CATEGORIES
        and has_permission(db, user, permission)
    ):
        raise PermissionDenied()


def access_label(user: User) -> str:
    """What "All" means for this account in the selector."""
    return (
        "All Shops"
        if user.access_category == AccessCategory.COMPANY_ADMIN
        else "All Assigned Shops"
    )


def scope_filter(
    user: User, context: "ShopContext", column: ColumnElement[uuid.UUID]
) -> ColumnElement[bool]:
    """WHERE clause for a consolidated or single-shop query on ``column`` (a shop_id).

    One shop: that shop (already validated by ``resolve``) *and* still in scope.
    All Shops / All Assigned Shops: only shops in the user's scope, in SQL.
    """
    in_scope = column.in_(select(Shop.id).where(shop_access_condition(user)))
    if context.shop is None:
        return in_scope
    return (column == context.shop.id) & in_scope


# --- Options and resolution ----------------------------------------------------------


def _option_query(user: User) -> Select[tuple[uuid.UUID, str, str]]:
    return select(Shop.id, Shop.name, Shop.code).where(shop_access_condition(user))


def list_active_options(db: Session, user: User) -> tuple[list[ShopOption], int]:
    """Active shops for the operational selector, one indexed query. (items, total)."""
    base = _option_query(user).where(Shop.is_active.is_(True))
    total = int(db.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = db.execute(
        base.order_by(func.lower(Shop.name), func.lower(Shop.code), Shop.id).limit(MAX_OPTIONS)
    ).all()
    return [ShopOption(id=r.id, name=r.name, code=r.code) for r in rows], total


def parse_shop_id(raw: str | None) -> uuid.UUID | None:
    """None, "" and "all" mean All Shops. Anything else must be a UUID."""
    if raw is None:
        return None
    value = raw.strip()
    if value == "" or value.lower() == "all":
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        raise _invalid_id() from None


def resolve(
    db: Session,
    user: User,
    raw_shop_id: str | None,
    *,
    purpose: Purpose = Purpose.READ,
    require_single_shop: bool = False,
    permission: str | None = None,
) -> ShopContext:
    """Validate a requested shop context against the database (see module docstring).

    ``permission``: the module capability the caller needs (checked here too).
    """
    require_module(db, user, permission)
    shop_id = parse_shop_id(raw_shop_id)
    if shop_id is None:
        if require_single_shop:
            raise _shop_required()
        return ALL_SHOPS
    stmt = select(Shop.id, Shop.name, Shop.code, Shop.is_active).where(
        Shop.id == shop_id, shop_access_condition(user)
    )
    if purpose == Purpose.OPERATE:
        stmt = stmt.with_for_update(read=True, of=Shop)
    row = db.execute(stmt).one_or_none()
    if row is None:
        raise _not_found()
    if not row.is_active and purpose != Purpose.HISTORY:
        raise _inactive()
    return ShopContext(
        shop=ShopOption(id=row.id, name=row.name, code=row.code), is_active=bool(row.is_active)
    )


def resolve_operational_shop(
    db: Session, user: User, raw_shop_id: str | None, *, permission: str
) -> ShopContext:
    """Exactly one active, in-scope shop for a new operational write (row share-locked)."""
    return resolve(
        db,
        user,
        raw_shop_id,
        purpose=Purpose.OPERATE,
        require_single_shop=True,
        permission=permission,
    )


def resolve_historical_shop(
    db: Session, user: User, raw_shop_id: str | None, *, permission: str
) -> ShopContext:
    """An in-scope shop for read-only history; inactive shops are allowed."""
    return resolve(db, user, raw_shop_id, purpose=Purpose.HISTORY, permission=permission)


def selection_status(db: Session, user: User, raw_shop_id: str | None) -> tuple[str, ShopContext]:
    """For the selector: "all" | "active" | "inactive" | "not_found" | "invalid".

    Never raises for a bad selection; the browser is told to fall back.
    """
    try:
        context = resolve(db, user, raw_shop_id, purpose=Purpose.READ)
    except AppError as exc:
        status = {
            "invalid_shop_id": "invalid",
            "shop_not_found": "not_found",
            "shop_inactive": "inactive",
        }.get(exc.code)
        if status is None:
            raise
        return status, ALL_SHOPS
    return ("all" if context.shop is None else "active"), context
