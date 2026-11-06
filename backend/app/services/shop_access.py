"""User shop access: the one place that decides which shops an account may see.

Authorization for any shop-scoped operation is the intersection of
    authenticated Company account + valid subscription      (route guards)
  + module permission                                       (role, checked by caller / resolve)
  + shop scope                                              (this module)
  + shop status and purpose                                 (shop_context.resolve)

Scope by account:
- Company Admin (protected tier): every shop, by tier. Not editable.
- Company User, mode 'all':      every registered shop, including later ones.
- Company User, mode 'selected': only the shops in user_shop_assignments.
- Company User, mode 'none' or no row or anything unexpected: no shop (fail closed).
- Super Admin: never any Company shop.

``scope_condition`` returns a SQL expression evaluated by PostgreSQL inside the
caller's query, reading the access rows at query time. It is never computed
from browser state or cached claims, so a revocation applies on the very next
request. Future modules must filter with it (or ``scoped_shop_ids``) in the
query itself, never by dropping rows after fetching them.

Changing a user's access (``set_access``) is Company Admin only, atomic,
versioned (stale forms get 409) and audited; a no-op save writes nothing.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, Select, and_, delete, exists, false, func, or_, select, true
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import AccessCategory, AuditEvent, Shop, User, UserShopAccess, UserShopAssignment
from app.models.shop_access import ACCESS_MODES, MODE_ALL, MODE_NONE, MODE_SELECTED

logger = logging.getLogger(__name__)

MODE_COMPANY = "company"  # the Company Admin's tier scope (not a stored mode)
MAX_ASSIGNED_SHOPS = 5_000
AUDIT_ACTION = "company_user.shop_access_changed"


# --- Errors -------------------------------------------------------------------------------


def _protected() -> AppError:
    return AppError(
        403,
        "protected_admin",
        "The Company Admin always has access to all shops; this cannot be changed.",
    )


def _invalid(message: str) -> AppError:
    return AppError(422, "invalid_shop_access", message)


def _stale() -> AppError:
    return AppError(
        409,
        "stale_shop_access",
        "This user's shop access was changed after the form was opened. Review the latest "
        "assignment and try again.",
    )


# --- Reading ----------------------------------------------------------------------------


@dataclass(frozen=True)
class AccessSummary:
    mode: str  # company | all | selected | none
    shop_count: int | None  # selected mode only
    version: int | None  # None for the Company Admin (not editable)
    updated_at: datetime | None


def _stored_mode(row: UserShopAccess | None) -> str:
    if row is None or row.access_mode not in ACCESS_MODES:
        if row is not None:
            logger.error("unexpected shop access mode", extra={"user_id": str(row.user_id)})
        return MODE_NONE  # fail closed
    return row.access_mode


def summary_for(db: Session, user: User) -> AccessSummary:
    if user.access_category == AccessCategory.COMPANY_ADMIN:
        return AccessSummary(MODE_COMPANY, None, None, None)
    if user.access_category != AccessCategory.COMPANY_USER:
        return AccessSummary(MODE_NONE, None, None, None)
    row = db.get(UserShopAccess, user.id)
    mode = _stored_mode(row)
    count = None
    if mode == MODE_SELECTED:
        count = int(
            db.scalar(
                select(func.count())
                .select_from(UserShopAssignment)
                .where(UserShopAssignment.user_id == user.id)
            )
            or 0
        )
    return AccessSummary(mode, count, row.version if row else None, row.updated_at if row else None)


def summaries_for(db: Session, users: list[User]) -> dict[uuid.UUID, AccessSummary]:
    """Bulk version for user lists: two queries, whatever the page size."""
    ids = [u.id for u in users if u.access_category == AccessCategory.COMPANY_USER]
    rows = (
        {
            r.user_id: r
            for r in db.scalars(select(UserShopAccess).where(UserShopAccess.user_id.in_(ids)))
        }
        if ids
        else {}
    )
    counts: dict[uuid.UUID, int] = {}
    if ids:
        for user_id, n in db.execute(
            select(UserShopAssignment.user_id, func.count())
            .where(UserShopAssignment.user_id.in_(ids))
            .group_by(UserShopAssignment.user_id)
        ).all():
            counts[user_id] = int(n)
    out: dict[uuid.UUID, AccessSummary] = {}
    for u in users:
        if u.access_category == AccessCategory.COMPANY_ADMIN:
            out[u.id] = AccessSummary(MODE_COMPANY, None, None, None)
            continue
        row = rows.get(u.id)
        mode = _stored_mode(row)
        out[u.id] = AccessSummary(
            mode,
            int(counts.get(u.id, 0)) if mode == MODE_SELECTED else None,
            row.version if row else None,
            row.updated_at if row else None,
        )
    return out


# --- Query scoping ----------------------------------------------------------------------


def scope_condition(
    user: User, shop_id_column: ColumnElement[uuid.UUID] | None = None
) -> ColumnElement[bool]:
    """SQL condition: ``shop_id_column`` (default ``shops.id``) is within the user's scope.

    Evaluated by PostgreSQL against the current access rows.
    """
    column = shop_id_column if shop_id_column is not None else Shop.id
    if not user.is_active:
        return false()
    if user.access_category == AccessCategory.COMPANY_ADMIN:
        return true()
    if user.access_category != AccessCategory.COMPANY_USER:
        return false()
    mode_is = lambda mode: exists().where(  # noqa: E731
        UserShopAccess.user_id == user.id, UserShopAccess.access_mode == mode
    )
    assigned = select(UserShopAssignment.shop_id).where(UserShopAssignment.user_id == user.id)
    return or_(mode_is(MODE_ALL), and_(mode_is(MODE_SELECTED), column.in_(assigned)))


def scoped_shop_ids(user: User, *, include_inactive: bool = False) -> Select[tuple[uuid.UUID]]:
    """Subquery of shop IDs the user may see; embed it, e.g. ``Sales.shop_id.in_(...)``.

    Active shops only unless ``include_inactive`` (historical reads).
    """
    stmt = select(Shop.id).where(scope_condition(user))
    if not include_inactive:
        stmt = stmt.where(Shop.is_active.is_(True))
    return stmt


# --- Company Admin management -----------------------------------------------------------


@dataclass(frozen=True)
class AssignedShop:
    id: uuid.UUID
    name: str
    code: str
    is_active: bool


@dataclass(frozen=True)
class AccessDetail:
    summary: AccessSummary
    shops: list[AssignedShop]  # selected mode only, by name then code


def detail_for(db: Session, user: User) -> AccessDetail:
    summary = summary_for(db, user)
    shops: list[AssignedShop] = []
    if summary.mode == MODE_SELECTED:
        rows = db.execute(
            select(Shop.id, Shop.name, Shop.code, Shop.is_active)
            .join(UserShopAssignment, UserShopAssignment.shop_id == Shop.id)
            .where(UserShopAssignment.user_id == user.id)
            .order_by(func.lower(Shop.name), func.lower(Shop.code), Shop.id)
        ).all()
        shops = [AssignedShop(r.id, r.name, r.code, bool(r.is_active)) for r in rows]
    return AccessDetail(summary, shops)


def assignable_shops(db: Session) -> list[AssignedShop]:
    """Every registered shop (ID, name, code, status) for the assignment checklist."""
    rows = db.execute(
        select(Shop.id, Shop.name, Shop.code, Shop.is_active).order_by(
            Shop.is_active.desc(), func.lower(Shop.name), func.lower(Shop.code), Shop.id
        )
    ).all()
    return [AssignedShop(r.id, r.name, r.code, bool(r.is_active)) for r in rows]


def validate_request(mode: str, shop_ids: list[uuid.UUID]) -> frozenset[uuid.UUID]:
    if mode not in ACCESS_MODES:
        raise _invalid("Choose All Shops, Selected Shops Only or No Shop Access.")
    unique = frozenset(shop_ids)
    if mode != MODE_SELECTED:
        if unique:
            raise _invalid("Shops can be listed only with Selected Shops Only.")
        return unique
    if not unique:
        raise _invalid("Select at least one shop, or choose another access option.")
    if len(unique) > MAX_ASSIGNED_SHOPS:
        raise _invalid(f"At most {MAX_ASSIGNED_SHOPS:,} shops can be selected.")
    return unique


def _check_shops_exist(db: Session, shop_ids: frozenset[uuid.UUID]) -> None:
    if not shop_ids:
        return
    found = set(db.scalars(select(Shop.id).where(Shop.id.in_(shop_ids))))
    if found != set(shop_ids):
        raise _invalid("One or more selected shops no longer exist. Reload and try again.")


def create_initial_access(
    db: Session, *, actor: User, user: User, mode: str, shop_ids: list[uuid.UUID]
) -> None:
    """Inside the user-creation transaction (the caller commits). Default: none."""
    wanted = validate_request(mode, shop_ids)
    _check_shops_exist(db, wanted)
    db.add(
        UserShopAccess(user_id=user.id, access_mode=mode, version=1, updated_by_user_id=actor.id)
    )
    db.flush()
    for shop_id in sorted(wanted):
        db.add(UserShopAssignment(user_id=user.id, shop_id=shop_id, assigned_by_user_id=actor.id))
    if mode != MODE_NONE:
        _audit(db, actor, user, MODE_NONE, frozenset(), mode, wanted, version=1)


def _audit(
    db: Session,
    actor: User,
    target: User,
    old_mode: str,
    old_ids: frozenset[uuid.UUID],
    new_mode: str,
    new_ids: frozenset[uuid.UUID],
    *,
    version: int,
) -> None:
    db.add(
        AuditEvent(
            action=AUDIT_ACTION,
            actor=f"user:{actor.id}",
            target_user_id=target.id,
            details={
                "previous_mode": old_mode,
                "new_mode": new_mode,
                "previous_shop_ids": sorted(str(i) for i in old_ids),
                "new_shop_ids": sorted(str(i) for i in new_ids),
                "added": len(new_ids - old_ids),
                "removed": len(old_ids - new_ids),
                "version": version,
            },
        )
    )


def set_access(
    db: Session,
    *,
    actor: User,
    target: User,
    mode: str,
    shop_ids: list[uuid.UUID],
    expected_version: int,
) -> tuple[AccessDetail, bool]:
    """Replace a Company User's shop access atomically. Returns (detail, changed).

    The caller passes ``target`` already locked (SELECT ... FOR UPDATE on the
    user row), so concurrent saves for one user are serialized.
    """
    if target.access_category == AccessCategory.COMPANY_ADMIN:
        raise _protected()
    if target.access_category != AccessCategory.COMPANY_USER:
        raise AppError(404, "user_not_found", "User not found.")
    wanted = validate_request(mode, shop_ids)
    try:
        row = db.scalar(
            select(UserShopAccess).where(UserShopAccess.user_id == target.id).with_for_update()
        )
        if row is None:  # fail-closed repair: a missing row means No Shop Access
            row = UserShopAccess(user_id=target.id, access_mode=MODE_NONE, version=1)
            db.add(row)
            db.flush()
        old_mode = _stored_mode(row)
        old_ids = frozenset(
            db.scalars(
                select(UserShopAssignment.shop_id).where(UserShopAssignment.user_id == target.id)
            )
        )
        if old_mode == mode and old_ids == wanted:
            db.commit()  # nothing to change: no version bump, no audit (duplicate-submit safe)
            return detail_for(db, target), False
        if row.version != expected_version:
            raise _stale()
        _check_shops_exist(db, wanted - old_ids)
        removed = old_ids - wanted if mode == MODE_SELECTED else old_ids
        if removed:
            db.execute(
                delete(UserShopAssignment).where(
                    UserShopAssignment.user_id == target.id,
                    UserShopAssignment.shop_id.in_(removed),
                )
            )
        # Mode first, then new rows: assignments may only point at a 'selected' row.
        row.access_mode = mode
        row.version += 1
        row.updated_by_user_id = actor.id
        db.flush()
        for shop_id in sorted(wanted - old_ids):
            db.add(
                UserShopAssignment(user_id=target.id, shop_id=shop_id, assigned_by_user_id=actor.id)
            )
        _audit(db, actor, target, old_mode, old_ids, mode, wanted, version=row.version)
        db.commit()
    except Exception:
        db.rollback()
        raise
    logger.info(
        "shop access changed by %s",
        actor.id,
        extra={"user_id": str(target.id), "mode": mode, "shops": len(wanted)},
    )
    return detail_for(db, target), True
