"""Shop Management.

Fields (from the requirements): Shop Name, POS ID, Branch Name, Code, FBR Token.

Rules:
- Shop Code and POS ID are unique across all shops, case-insensitively
  (PostgreSQL unique indexes on lower(...)); the display form is preserved.
  A pre-check gives friendly errors; the indexes are the guarantee, so
  concurrent duplicates fail with the same 409.
- POS ID is a string (leading zeros kept). No FBR-specific format is assumed:
  1-50 letters, digits, hyphens or underscores, starting with a letter/digit.
- FBR token: optional at creation ("Token not configured" is an explicit
  state), set or replaced only through the token operation, stored only as
  AES-256-GCM ciphertext under the separate FBR keyring, never returned,
  logged or audited. Blank never clears an existing token.
- Shops are never deleted. Deactivation keeps the record, its identity and
  its FBR configuration; inactive shops will not be selectable for new uploads.
- Every edit carries ``expected_version``; a stale form gets 409.
- Creation is bounded by the Super Admin's Shop Allowance
  (``app.services.shop_allowance``): the allowance row is locked before the
  insert, active and inactive shops both count, and the database trigger
  ``shops_enforce_allowance`` backs this up for any other write path.
"""

import logging
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import clock, secret_box
from app.core.errors import AppError
from app.models import AuditEvent, Shop, User
from app.services import shop_allowance

logger = logging.getLogger(__name__)

TOKEN_PURPOSE = "shops.fbr_token"
NAME_MAX = 120
CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,19}$")
POS_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,49}$")
TOKEN_MIN, TOKEN_MAX = 8, 2048
SORT_FIELDS = ("name", "code", "branch", "pos_id", "status", "created")


# --- Errors -----------------------------------------------------------------------


def _invalid(field: str, message: str) -> AppError:
    return AppError(422, f"invalid_{field}", message)


def _not_found() -> AppError:
    return AppError(404, "shop_not_found", "Shop not found.")


def _stale() -> AppError:
    return AppError(
        409,
        "stale_shop",
        "This shop was changed after the form was opened. Reload and try again.",
    )


def _code_taken() -> AppError:
    return AppError(409, "shop_code_taken", "Another shop already uses this Shop Code.")


def _pos_taken() -> AppError:
    return AppError(409, "pos_id_taken", "Another shop already uses this POS ID.")


def _key_missing() -> AppError:
    return AppError(
        503,
        "fbr_key_missing",
        "FBR token encryption is not set up on the server. An administrator must set "
        "FBR_TOKEN_ENCRYPTION_KEY (see the README) and restart the backend.",
    )


def _conflict_from(exc: IntegrityError) -> AppError:
    text = str(exc.orig)
    if "shops_within_allowance" in text or "shop_limit_reached" in text:
        return AppError(
            409,
            "shop_limit_reached",
            "Shop limit reached. The shop allowance is managed by the Super Admin.",
        )
    if "uq_shops_code_lower" in text:
        return _code_taken()
    if "uq_shops_pos_id_lower" in text:
        return _pos_taken()
    return AppError(409, "shop_conflict", "The shop could not be saved because of a conflict.")


# --- Validation ---------------------------------------------------------------------


def _has_control(value: str) -> bool:
    return any(ord(c) < 32 or ord(c) == 127 for c in value)


def clean_text(raw: str, field: str, label: str) -> str:
    if _has_control(raw):
        raise _invalid(field, f"{label} contains characters that are not allowed.")
    value = " ".join(raw.split())
    if not value:
        raise _invalid(field, f"Enter the {label.lower()}.")
    if len(value) > NAME_MAX:
        raise _invalid(field, f"{label} must be at most {NAME_MAX} characters.")
    return value


def clean_code(raw: str) -> str:
    value = raw.strip()
    if not CODE_RE.match(value):
        raise _invalid(
            "code",
            "Shop Code must be 1-20 letters, digits, hyphens or underscores, "
            "starting with a letter or digit.",
        )
    return value


def clean_pos_id(raw: str) -> str:
    value = raw.strip()
    if not POS_ID_RE.match(value):
        raise _invalid(
            "pos_id",
            "POS ID must be 1-50 letters, digits, hyphens or underscores, "
            "starting with a letter or digit.",
        )
    return value


def clean_token(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise _invalid("fbr_token", "Enter the FBR token.")
    if not (TOKEN_MIN <= len(value) <= TOKEN_MAX):
        raise _invalid("fbr_token", f"The FBR token must be {TOKEN_MIN}-{TOKEN_MAX} characters.")
    if any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
        raise _invalid(
            "fbr_token", "The FBR token may contain only printable characters without spaces."
        )
    return value


def _encrypt(token: str) -> str:
    try:
        return secret_box.encrypt(token, TOKEN_PURPOSE, secret_box.FBR)
    except secret_box.EncryptionKeyError:
        logger.error("shops: FBR token encryption key missing or invalid")
        raise _key_missing() from None


def token_status(shop: Shop) -> str:
    """configured | not_configured | unreadable (key not available)."""
    if shop.encrypted_fbr_token is None:
        return "not_configured"
    if not secret_box.key_available_for(shop.encrypted_fbr_token, secret_box.FBR):
        return "unreadable"
    return "configured"


# --- Reading --------------------------------------------------------------------------


@dataclass(frozen=True)
class ShopCounts:
    total: int
    active: int

    @property
    def inactive(self) -> int:
        return self.total - self.active


def counts(db: Session) -> ShopCounts:
    total, active = db.execute(
        select(func.count(), func.count().filter(Shop.is_active.is_(True))).select_from(Shop)
    ).one()
    return ShopCounts(int(total), int(active))


def get_shop(db: Session, shop_id: uuid.UUID, *, lock: bool = False) -> Shop:
    stmt: Select[tuple[Shop]] = select(Shop).where(Shop.id == shop_id)
    if lock:
        stmt = stmt.with_for_update()
    shop = db.scalar(stmt)
    if shop is None:
        raise _not_found()
    return shop


def list_shops(
    db: Session,
    *,
    search: str | None,
    status: str | None,
    sort: str,
    order: str,
    limit: int,
    offset: int,
) -> tuple[list[Shop], int]:
    stmt = select(Shop)
    if search and search.strip():
        pattern = "%" + search.strip().lower().replace("%", r"\%").replace("_", r"\_") + "%"
        stmt = stmt.where(
            or_(
                func.lower(Shop.name).like(pattern, escape="\\"),
                func.lower(Shop.code).like(pattern, escape="\\"),
                func.lower(Shop.branch_name).like(pattern, escape="\\"),
                func.lower(Shop.pos_id).like(pattern, escape="\\"),
            )
        )
    if status == "active":
        stmt = stmt.where(Shop.is_active.is_(True))
    elif status == "inactive":
        stmt = stmt.where(Shop.is_active.is_(False))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    column = {
        "name": func.lower(Shop.name),
        "code": func.lower(Shop.code),
        "branch": func.lower(Shop.branch_name),
        "pos_id": func.lower(Shop.pos_id),
        "status": Shop.is_active,
        "created": Shop.created_at,
    }[sort]
    ordered = column.desc() if order == "desc" else column.asc()
    rows = db.scalars(stmt.order_by(ordered, Shop.id).limit(limit).offset(offset)).all()
    return list(rows), int(total)


# --- Writing --------------------------------------------------------------------------


def _audit(db: Session, actor: User, action: str, shop: Shop, extra: dict[str, object]) -> None:
    db.add(
        AuditEvent(
            action=action,
            actor=f"user:{actor.id}",
            details={"shop_id": str(shop.id), "code": shop.code, **extra},
        )
    )


def _check_unique(db: Session, code: str, pos_id: str, exclude: uuid.UUID | None = None) -> None:
    def taken(column: object, value: str) -> bool:
        stmt = select(Shop.id).where(func.lower(column) == value.lower())  # type: ignore[arg-type]
        if exclude is not None:
            stmt = stmt.where(Shop.id != exclude)
        return db.scalar(stmt) is not None

    if taken(Shop.code, code):
        raise _code_taken()
    if taken(Shop.pos_id, pos_id):
        raise _pos_taken()


def create_shop(
    db: Session,
    *,
    actor: User,
    name: str,
    branch_name: str,
    code: str,
    pos_id: str,
    fbr_token: str | None,
) -> Shop:
    clean_name = clean_text(name, "name", "Shop Name")
    clean_branch = clean_text(branch_name, "branch_name", "Branch Name")
    clean_shop_code = clean_code(code)
    clean_pos = clean_pos_id(pos_id)
    ciphertext = _encrypt(clean_token(fbr_token)) if fbr_token else None
    try:
        # Takes the allowance lock for the rest of this transaction.
        shop_allowance.ensure_capacity(db)
        _check_unique(db, clean_shop_code, clean_pos)
        now = clock.utcnow()
        shop = Shop(
            name=clean_name,
            branch_name=clean_branch,
            code=clean_shop_code,
            pos_id=clean_pos,
            encrypted_fbr_token=ciphertext,
            fbr_token_updated_at=now if ciphertext else None,
            is_active=True,
            version=1,
            created_by_user_id=actor.id,
            updated_by_user_id=actor.id,
        )
        db.add(shop)
        db.flush()
        _audit(db, actor, "shop.created", shop, {"fbr_token_configured": ciphertext is not None})
        if ciphertext:
            _audit(db, actor, "shop.fbr_token_configured", shop, {})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _conflict_from(exc) from None
    except Exception:
        db.rollback()
        raise
    logger.info("shop created by %s", actor.id, extra={"shop_id": str(shop.id)})
    return shop


def update_shop(
    db: Session,
    *,
    actor: User,
    shop_id: uuid.UUID,
    expected_version: int,
    name: str | None,
    branch_name: str | None,
    code: str | None,
    pos_id: str | None,
) -> Shop:
    """Profile fields only; the FBR token has its own operation."""
    try:
        shop = get_shop(db, shop_id, lock=True)
        if shop.version != expected_version:
            raise _stale()
        changes: dict[str, str] = {}
        if name is not None:
            changes["name"] = clean_text(name, "name", "Shop Name")
        if branch_name is not None:
            changes["branch_name"] = clean_text(branch_name, "branch_name", "Branch Name")
        if code is not None:
            changes["code"] = clean_code(code)
        if pos_id is not None:
            changes["pos_id"] = clean_pos_id(pos_id)
        changed = sorted(k for k, v in changes.items() if getattr(shop, k) != v)
        if not changed:
            db.rollback()
            return get_shop(db, shop_id)
        _check_unique(
            db, changes.get("code", shop.code), changes.get("pos_id", shop.pos_id), exclude=shop.id
        )
        for key in changed:
            setattr(shop, key, changes[key])
        shop.version += 1
        shop.updated_by_user_id = actor.id
        _audit(db, actor, "shop.updated", shop, {"changed": changed, "version": shop.version})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _conflict_from(exc) from None
    except Exception:
        db.rollback()
        raise
    return shop


def set_fbr_token(
    db: Session, *, actor: User, shop_id: uuid.UUID, expected_version: int, token: str
) -> Shop:
    """Configure or replace the token. There is no way to clear it through the API."""
    ciphertext = _encrypt(clean_token(token))
    try:
        shop = get_shop(db, shop_id, lock=True)
        if shop.version != expected_version:
            raise _stale()
        replacing = shop.encrypted_fbr_token is not None
        shop.encrypted_fbr_token = ciphertext
        shop.fbr_token_updated_at = clock.utcnow()
        shop.version += 1
        shop.updated_by_user_id = actor.id
        _audit(
            db,
            actor,
            "shop.fbr_token_replaced" if replacing else "shop.fbr_token_configured",
            shop,
            {"version": shop.version},
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    logger.info("shop FBR token set by %s", actor.id, extra={"shop_id": str(shop_id)})
    return shop


def set_active(
    db: Session, *, actor: User, shop_id: uuid.UUID, expected_version: int, active: bool
) -> Shop:
    """Deactivate / reactivate. Never deletes; never touches the FBR token."""
    try:
        shop = get_shop(db, shop_id, lock=True)
        if shop.version != expected_version:
            raise _stale()
        if shop.is_active == active:
            db.rollback()
            return get_shop(db, shop_id)
        shop.is_active = active
        shop.version += 1
        shop.updated_by_user_id = actor.id
        _audit(
            db,
            actor,
            "shop.reactivated" if active else "shop.deactivated",
            shop,
            {"version": shop.version},
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return shop


def record_token_denial(db: Session, actor: User, shop_id: uuid.UUID | None) -> None:
    """Audit an attempt to manage an FBR token without the permission."""
    try:
        db.add(
            AuditEvent(
                action="shop.fbr_token_denied",
                actor=f"user:{actor.id}",
                details={"shop_id": str(shop_id) if shop_id else None},
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("could not record FBR token denial")
