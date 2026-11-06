"""Shop Allowance (Super Admin controls it; the Company works within it).

Rules:
- Mode ``limited`` needs a whole number of shops >= 1; mode ``unlimited`` has
  no number at all (never 0, -1 or a "very large" sentinel). The database
  CHECK constraint rejects any other combination.
- Every registered shop uses one slot, active or inactive. Deactivating never
  frees a slot; reactivating never takes one (it inserts nothing).
- Lowering the allowance below current usage keeps every shop untouched; only
  new registrations are blocked until usage is below the allowance again.

Concurrency: the singleton ``shop_allowance`` row is the single lock
(``SELECT ... FOR UPDATE``). ``ensure_capacity`` takes it inside the shop
creation transaction before counting, and ``update_allowance`` takes it before
changing the limit, so creations and changes are serialized and the count is
always read after the previous holder committed. The ``shops_enforce_allowance``
trigger (migration 0009) takes the same lock first, so other write paths are
serialized identically and lock order is always the same (no deadlocks).

Privacy: everything here is aggregate. No function returns or audits shop
names, codes, POS IDs, branches, IDs or tokens.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import AuditEvent, Shop, User
from app.models.shop_allowance import LIMITED, SINGLETON_ID, UNLIMITED, ShopAllowance

logger = logging.getLogger(__name__)

# A typo guard for limited mode (Integer column). Anyone needing more uses Unlimited.
MAX_LIMIT = 100_000
MODES = (LIMITED, UNLIMITED)
AUDIT_ACTION = "shop_allowance.changed"


@dataclass(frozen=True)
class AllowanceUsage:
    mode: str
    max_shops: int | None
    registered: int
    version: int
    updated_at: datetime | None  # None until the Super Admin first changes it

    @property
    def unlimited(self) -> bool:
        return self.mode == UNLIMITED

    @property
    def available(self) -> int | None:
        if self.max_shops is None:
            return None
        return max(0, self.max_shops - self.registered)

    @property
    def at_capacity(self) -> bool:
        return self.max_shops is not None and self.registered >= self.max_shops

    @property
    def over_limit(self) -> bool:
        return self.max_shops is not None and self.registered > self.max_shops


# --- Errors -------------------------------------------------------------------------


def _missing() -> AppError:
    return AppError(
        503,
        "shop_allowance_missing",
        "The shop allowance record is missing. Run the database migrations "
        "(alembic upgrade head) and try again.",
    )


def _invalid(message: str) -> AppError:
    return AppError(422, "invalid_shop_allowance", message)


def _stale() -> AppError:
    return AppError(
        409,
        "stale_shop_allowance",
        "The shop allowance was changed after this form was opened. Review the latest "
        "values and try again.",
    )


def limit_reached(max_shops: int, registered: int) -> AppError:
    return AppError(
        409,
        "shop_limit_reached",
        f"Shop limit reached: {registered} of {max_shops} allowed shops are registered "
        "(inactive shops count too). The shop allowance is managed by the Super Admin.",
    )


# --- Reading --------------------------------------------------------------------------


def _row(db: Session, *, lock: bool) -> ShopAllowance:
    stmt = select(ShopAllowance).where(ShopAllowance.id == SINGLETON_ID)
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if row is None:
        logger.error("shop allowance row is missing")
        raise _missing()
    return row


def _registered(db: Session) -> int:
    """All registered shops, active and inactive."""
    return int(db.scalar(select(func.count()).select_from(Shop)) or 0)


def _usage(row: ShopAllowance, registered: int) -> AllowanceUsage:
    return AllowanceUsage(
        mode=row.mode,
        max_shops=row.max_shops,
        registered=registered,
        version=row.version,
        updated_at=row.updated_at
        if row.updated_by_user_id is not None or row.version > 1
        else None,
    )


def get_usage(db: Session) -> AllowanceUsage:
    return _usage(_row(db, lock=False), _registered(db))


# --- Enforcement ----------------------------------------------------------------------


def ensure_capacity(db: Session) -> None:
    """Call inside the shop-creation transaction, before inserting.

    Locks the allowance row until that transaction ends, then counts. Raises
    ``shop_limit_reached`` (409) when a finite allowance is already used up.
    """
    row = _row(db, lock=True)
    if row.mode == UNLIMITED or row.max_shops is None:
        return
    registered = _registered(db)
    if registered >= row.max_shops:
        raise limit_reached(row.max_shops, registered)


# --- Super Admin update ---------------------------------------------------------------


def validate(mode: str, max_shops: int | None) -> int | None:
    if mode not in MODES:
        raise _invalid("Choose Limited Shops or Unlimited Shops.")
    if mode == UNLIMITED:
        if max_shops is not None:
            raise _invalid("Unlimited Shops has no maximum. Remove the number or choose Limited.")
        return None
    if max_shops is None or isinstance(max_shops, bool) or not isinstance(max_shops, int):
        raise _invalid("Enter the maximum number of shops as a whole number.")
    if max_shops < 1:
        raise _invalid("The maximum number of shops must be at least 1.")
    if max_shops > MAX_LIMIT:
        raise _invalid(
            f"The maximum number of shops must be at most {MAX_LIMIT:,}. "
            "Choose Unlimited Shops for no limit."
        )
    return max_shops


def update_allowance(
    db: Session, *, actor: User, mode: str, max_shops: int | None, expected_version: int
) -> tuple[AllowanceUsage, bool]:
    """Change the allowance. Returns (usage, changed).

    Stale forms get 409, except a resubmission whose values already match the
    stored ones, which is answered as unchanged (duplicate-submit safe).
    Never touches shops, the subscription or renewal history.
    """
    new_max = validate(mode, max_shops)
    try:
        row = _row(db, lock=True)
        registered = _registered(db)
        same = row.mode == mode and row.max_shops == new_max
        if same:
            usage = _usage(row, registered)
            db.rollback()
            return usage, False
        if row.version != expected_version:
            raise _stale()
        previous = {"mode": row.mode, "max_shops": row.max_shops}
        row.mode = mode
        row.max_shops = new_max
        row.version += 1
        row.updated_by_user_id = actor.id
        db.add(
            AuditEvent(
                action=AUDIT_ACTION,
                actor=f"user:{actor.id}",
                details={
                    "previous_mode": previous["mode"],
                    "previous_max_shops": previous["max_shops"],
                    "new_mode": mode,
                    "new_max_shops": new_max,
                    "registered_shops": registered,
                    "version": row.version,
                },
            )
        )
        db.commit()
        db.refresh(row)
        usage = _usage(row, registered)
    except Exception:
        db.rollback()
        raise
    logger.info(
        "shop allowance changed by %s",
        actor.id,
        extra={"mode": mode, "max_shops": new_max, "version": usage.version},
    )
    return usage, True
