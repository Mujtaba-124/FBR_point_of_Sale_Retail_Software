"""Company User Management (Company Admin only).

Capacity: at most ``MAX_ACTIVE_COMPANY_ACCOUNTS`` (15) active Company
Workspace accounts, the protected Company Admin included; Super Admins are not
counted and inactive accounts free their slot. Every operation that can add an
active account takes the same PostgreSQL transaction-level advisory lock and
counts inside it, so concurrent requests are serialized and cannot exceed the
limit. A database trigger (migration 0007) enforces the same rule as a final
guarantee for any other write path.

The protected Company Admin cannot be deactivated, demoted or given another
role through this module, and no Company Admin can be created here.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import AppError
from app.core.security import EMAIL_MAX_LENGTH, is_valid_email, normalize_email
from app.models import (
    AccessCategory,
    AuditEvent,
    AuthenticationSession,
    CompanyRole,
    User,
)
from app.models.company_roles import SYSTEM_COMPANY_ADMIN
from app.services import shop_access
from app.services.password_setup import has_open_link, issue_setup_token, unusable_password_hash

logger = logging.getLogger(__name__)

MAX_ACTIVE_COMPANY_ACCOUNTS = 15
LIMIT_LOCK_KEY = 4801500015  # same key as the database trigger
COMPANY_TIERS = (AccessCategory.COMPANY_ADMIN, AccessCategory.COMPANY_USER)
NAME_MAX_LENGTH = 200
SORT_FIELDS = ("name", "email", "role", "status", "last_login", "created")


# --- Errors ----------------------------------------------------------------------


def limit_reached() -> AppError:
    return AppError(
        409,
        "user_limit_reached",
        f"All {MAX_ACTIVE_COMPANY_ACCOUNTS} active user slots are in use. Deactivate a user "
        "to free a slot.",
    )


def _not_found() -> AppError:
    return AppError(404, "user_not_found", "User not found.")


def _protected() -> AppError:
    return AppError(
        403,
        "protected_admin",
        "The Company Admin is a protected account and cannot be changed here.",
    )


def _invalid(message: str) -> AppError:
    return AppError(422, "invalid_user", message)


def _is_limit_violation(exc: IntegrityError) -> bool:
    return "company_user_limit_reached" in str(exc.orig)


# --- Capacity ----------------------------------------------------------------------


@dataclass(frozen=True)
class Capacity:
    active: int
    inactive: int
    limit: int = MAX_ACTIVE_COMPANY_ACCOUNTS

    @property
    def available(self) -> int:
        return max(0, self.limit - self.active)


def capacity(db: Session) -> Capacity:
    rows = db.execute(
        select(User.is_active, func.count())
        .where(User.access_category.in_(COMPANY_TIERS))
        .group_by(User.is_active)
    ).all()
    counts = {bool(active): int(n) for active, n in rows}
    return Capacity(active=counts.get(True, 0), inactive=counts.get(False, 0))


def _lock_capacity(db: Session) -> None:
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LIMIT_LOCK_KEY})


def _ensure_slot(db: Session, actor: User, operation: str) -> None:
    """Call with the capacity lock held."""
    if capacity(db).active >= MAX_ACTIVE_COMPANY_ACCOUNTS:
        db.rollback()
        # Separate transaction: the refusal is worth recording, the request is not.
        db.add(
            AuditEvent(
                action="company_user.limit_reached",
                actor=f"user:{actor.id}",
                details={"operation": operation, "limit": MAX_ACTIVE_COMPANY_ACCOUNTS},
            )
        )
        db.commit()
        raise limit_reached()


# --- Reading -------------------------------------------------------------------------


@dataclass(frozen=True)
class UserView:
    user: User
    role: CompanyRole | None
    setup_link_expires_at: datetime | None
    shop_access: shop_access.AccessSummary

    @property
    def is_protected(self) -> bool:
        return self.user.access_category == AccessCategory.COMPANY_ADMIN


def _company_users() -> Select[tuple[User]]:
    return select(User).where(User.access_category.in_(COMPANY_TIERS))


def _view(db: Session, user: User, access: shop_access.AccessSummary | None = None) -> UserView:
    role = db.get(CompanyRole, user.company_role_id) if user.company_role_id else None
    expires = has_open_link(db, user.id) if user.must_set_password else None
    return UserView(user, role, expires, access or shop_access.summary_for(db, user))


def get_company_user(db: Session, user_id: uuid.UUID, *, lock: bool = False) -> User:
    stmt = _company_users().where(User.id == user_id)
    if lock:
        stmt = stmt.with_for_update()
    user = db.scalar(stmt)
    if user is None:  # unknown, or a Super Admin: never exposed here
        raise _not_found()
    return user


def get_user_view(db: Session, user_id: uuid.UUID) -> UserView:
    return _view(db, get_company_user(db, user_id))


def list_users(
    db: Session,
    *,
    search: str | None,
    status: str | None,
    role_id: uuid.UUID | None,
    sort: str,
    order: str,
    limit: int,
    offset: int,
) -> tuple[list[UserView], int]:
    stmt = _company_users().outerjoin(CompanyRole, CompanyRole.id == User.company_role_id)
    if search:
        pattern = "%" + search.strip().lower().replace("%", r"\%").replace("_", r"\_") + "%"
        stmt = stmt.where(
            or_(
                func.lower(User.full_name).like(pattern, escape="\\"),
                func.lower(User.email).like(pattern, escape="\\"),
            )
        )
    if status == "active":
        stmt = stmt.where(User.is_active.is_(True))
    elif status == "inactive":
        stmt = stmt.where(User.is_active.is_(False))
    if role_id is not None:
        stmt = stmt.where(User.company_role_id == role_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    column = {
        "name": func.lower(User.full_name),
        "email": func.lower(User.email),
        "role": func.lower(CompanyRole.name),
        "status": User.is_active,
        "last_login": User.last_login_at,
        "created": User.created_at,
    }[sort]
    ordered = column.desc().nulls_last() if order == "desc" else column.asc().nulls_last()
    users = list(db.scalars(stmt.order_by(ordered, User.id).limit(limit).offset(offset)).all())
    access = shop_access.summaries_for(db, users)  # bulk: no per-row shop queries
    return [_view(db, u, access[u.id]) for u in users], int(total)


# --- Validation ------------------------------------------------------------------------


def _clean_name(raw: str) -> str:
    name = " ".join(raw.split())
    if not name:
        raise _invalid("Enter the full name.")
    if len(name) > NAME_MAX_LENGTH:
        raise _invalid(f"The full name must be at most {NAME_MAX_LENGTH} characters.")
    if any(ord(c) < 32 or ord(c) == 127 for c in raw):
        raise _invalid("The full name contains characters that are not allowed.")
    return name


def assignable_role(db: Session, role_id: uuid.UUID) -> CompanyRole:
    role = db.get(CompanyRole, role_id)
    if role is None:
        raise AppError(422, "invalid_role", "Choose a valid role.")
    if role.system_key == SYSTEM_COMPANY_ADMIN:
        raise AppError(
            422, "role_not_assignable", "The Company Admin role cannot be assigned to users."
        )
    if not role.is_active:
        raise AppError(422, "role_inactive", "This role has been retired. Choose another role.")
    return role


def _audit(
    db: Session, actor: User, action: str, target: User | None, details: dict[str, object]
) -> None:
    db.add(
        AuditEvent(
            action=action,
            actor=f"user:{actor.id}",
            target_user_id=target.id if target else None,
            details=details,
        )
    )


# --- Writing -----------------------------------------------------------------------------


@dataclass(frozen=True)
class CreatedUser:
    view: UserView
    setup_token: str
    setup_expires_at: datetime


def create_user(
    db: Session,
    *,
    actor: User,
    full_name: str,
    email: str,
    role_id: uuid.UUID,
    access_mode: str = shop_access.MODE_NONE,
    shop_ids: list[uuid.UUID] | None = None,
) -> CreatedUser:
    """New users get No Shop Access unless the Company Admin chooses otherwise."""
    name = _clean_name(full_name)
    address = normalize_email(email)
    if not is_valid_email(address) or len(address) > EMAIL_MAX_LENGTH:
        raise _invalid("Enter a valid email address.")
    shop_access.validate_request(access_mode, shop_ids or [])
    try:
        role = assignable_role(db, role_id)
        _lock_capacity(db)
        existing = db.scalar(select(User).where(func.lower(User.email) == address))
        if existing is not None:
            db.rollback()
            if existing.access_category == AccessCategory.COMPANY_USER and not existing.is_active:
                raise AppError(
                    409,
                    "email_belongs_to_inactive_user",
                    "An inactive user already has this email. Reactivate that user instead.",
                )
            raise AppError(
                409, "email_already_exists", "An account with this email already exists."
            )
        _ensure_slot(db, actor, "create")
        user = User(
            email=address,
            full_name=name,
            password_hash=unusable_password_hash(),
            access_category=AccessCategory.COMPANY_USER,
            company_role_id=role.id,
            is_active=True,
            must_set_password=True,
        )
        db.add(user)
        db.flush()
        shop_access.create_initial_access(
            db, actor=actor, user=user, mode=access_mode, shop_ids=shop_ids or []
        )
        token, expires = issue_setup_token(db, user, actor)
        _audit(
            db,
            actor,
            "company_user.created",
            user,
            {
                "role_id": str(role.id),
                "role": role.name,
                "setup_link_expires_at": expires.isoformat(),
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _is_limit_violation(exc):
            raise limit_reached() from None
        raise AppError(
            409, "email_already_exists", "An account with this email already exists."
        ) from None
    except Exception:
        db.rollback()
        raise
    logger.info("company user created by %s", actor.id, extra={"user_id": str(user.id)})
    return CreatedUser(_view(db, user), token, expires)


def update_user(
    db: Session,
    *,
    actor: User,
    user_id: uuid.UUID,
    full_name: str | None,
    role_id: uuid.UUID | None,
) -> UserView:
    try:
        user = get_company_user(db, user_id, lock=True)
        protected = user.access_category == AccessCategory.COMPANY_ADMIN
        changes: dict[str, object] = {}
        if full_name is not None:
            name = _clean_name(full_name)
            if name != user.full_name:
                user.full_name = name
                changes["full_name"] = True  # value omitted: personal data
        if role_id is not None and role_id != user.company_role_id:
            if protected:
                raise _protected()
            role = assignable_role(db, role_id)
            old_role = db.get(CompanyRole, user.company_role_id) if user.company_role_id else None
            user.company_role_id = role.id
            _audit(
                db,
                actor,
                "company_user.role_changed",
                user,
                {
                    "from_role": old_role.name if old_role else None,
                    "to_role": role.name,
                    "to_role_id": str(role.id),
                },
            )
        if changes:
            _audit(db, actor, "company_user.updated", user, {"changed": sorted(changes)})
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _view(db, user)


def deactivate_user(db: Session, *, actor: User, user_id: uuid.UUID) -> UserView:
    try:
        user = get_company_user(db, user_id, lock=True)
        if user.access_category == AccessCategory.COMPANY_ADMIN or user.id == actor.id:
            raise _protected()
        if user.is_active:
            user.is_active = False
            # Sessions are re-checked on every request anyway; revoke them too.
            db.execute(
                update(AuthenticationSession)
                .where(
                    AuthenticationSession.user_id == user.id,
                    AuthenticationSession.revoked_at.is_(None),
                )
                .values(revoked_at=clock.utcnow())
            )
            _audit(db, actor, "company_user.deactivated", user, {})
        db.commit()
    except Exception:
        db.rollback()
        raise
    logger.info("company user deactivated by %s", actor.id, extra={"user_id": str(user_id)})
    return _view(db, user)


def reactivate_user(db: Session, *, actor: User, user_id: uuid.UUID) -> UserView:
    try:
        _lock_capacity(db)
        user = get_company_user(db, user_id, lock=True)
        if not user.is_active:
            role = db.get(CompanyRole, user.company_role_id) if user.company_role_id else None
            if role is None or not role.is_active:
                raise AppError(
                    409,
                    "role_inactive",
                    "This user's role has been retired. Assign an active role first.",
                )
            _ensure_slot(db, actor, "reactivate")
            user = get_company_user(db, user_id, lock=True)
            user.is_active = True
            _audit(db, actor, "company_user.reactivated", user, {})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _is_limit_violation(exc):
            raise limit_reached() from None
        raise
    except Exception:
        db.rollback()
        raise
    logger.info("company user reactivated by %s", actor.id, extra={"user_id": str(user_id)})
    return _view(db, user)


def reissue_setup_link(db: Session, *, actor: User, user_id: uuid.UUID) -> CreatedUser:
    try:
        user = get_company_user(db, user_id, lock=True)
        if user.access_category == AccessCategory.COMPANY_ADMIN:
            raise _protected()
        if not user.must_set_password:
            raise AppError(409, "setup_not_pending", "This user has already set a password.")
        if not user.is_active:
            raise AppError(409, "user_inactive", "Reactivate the user before issuing a link.")
        token, expires = issue_setup_token(db, user, actor)
        _audit(
            db,
            actor,
            "company_user.setup_link_issued",
            user,
            {"setup_link_expires_at": expires.isoformat()},
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return CreatedUser(_view(db, user), token, expires)
