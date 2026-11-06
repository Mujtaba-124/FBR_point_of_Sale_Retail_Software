"""Company roles (Company Admin only).

- The two system roles are protected: they cannot be renamed, edited or
  retired here. Company Admin always has every capability; Company User has the
  Dashboard baseline.
- Custom roles carry assignable capabilities only (never User Management or
  Roles & Permissions). Unknown keys are rejected.
- Retiring a role still assigned to users requires a reassignment target, done
  in the same transaction, so no user is ever left on a retired role.
- Edits use optimistic concurrency (``expected_version``).
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import AccessCategory, AuditEvent, CompanyRole, CompanyRolePermission, User
from app.models.company_roles import SYSTEM_COMPANY_ADMIN
from app.services.permissions import ADMIN_ONLY_KEYS, ALL_KEYS, ASSIGNABLE_KEYS, BASELINE

logger = logging.getLogger(__name__)

NAME_MIN, NAME_MAX, DESCRIPTION_MAX = 2, 60, 300


def _invalid(message: str, code: str = "invalid_role") -> AppError:
    return AppError(422, code, message)


def _protected() -> AppError:
    return AppError(403, "protected_role", "System roles cannot be changed.")


def _not_found() -> AppError:
    return AppError(404, "role_not_found", "Role not found.")


@dataclass(frozen=True)
class RoleView:
    role: CompanyRole
    active_users: int
    total_users: int

    @property
    def permissions(self) -> list[str]:
        if self.role.system_key == SYSTEM_COMPANY_ADMIN:
            return sorted(ALL_KEYS)
        return sorted(BASELINE | (self.role.permission_keys & ASSIGNABLE_KEYS))


def _counts(db: Session) -> dict[uuid.UUID, tuple[int, int]]:
    rows = db.execute(
        select(
            User.company_role_id,
            func.count().filter(User.is_active.is_(True)),
            func.count(),
        )
        .where(User.company_role_id.is_not(None))
        .group_by(User.company_role_id)
    ).all()
    return {rid: (int(a), int(t)) for rid, a, t in rows}


def list_roles(db: Session) -> list[RoleView]:
    counts = _counts(db)
    roles = db.scalars(
        select(CompanyRole).order_by(
            CompanyRole.system_key.is_(None),  # system roles first
            CompanyRole.is_active.desc(),
            func.lower(CompanyRole.name),
        )
    ).all()
    return [RoleView(r, *counts.get(r.id, (0, 0))) for r in roles]


def get_role_view(db: Session, role_id: uuid.UUID) -> RoleView:
    role = db.get(CompanyRole, role_id)
    if role is None:
        raise _not_found()
    active, total = _counts(db).get(role.id, (0, 0))
    return RoleView(role, active, total)


def _clean_name(raw: str) -> str:
    name = " ".join(raw.split())
    if not (NAME_MIN <= len(name) <= NAME_MAX):
        raise _invalid(f"The role name must be {NAME_MIN}-{NAME_MAX} characters.")
    if any(ord(c) < 32 or ord(c) == 127 for c in raw):
        raise _invalid("The role name contains characters that are not allowed.")
    return name


def _clean_description(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = raw.strip()
    if len(text) > DESCRIPTION_MAX:
        raise _invalid(f"The description must be at most {DESCRIPTION_MAX} characters.")
    if any(ord(c) < 32 and c not in "\n\t" for c in text):
        raise _invalid("The description contains characters that are not allowed.")
    return text or None


def _clean_permissions(keys: list[str]) -> set[str]:
    requested = set(keys)
    unknown = sorted(requested - ALL_KEYS)
    if unknown:
        raise _invalid(f"Unknown permission: {', '.join(unknown[:5])}.", "invalid_permission")
    admin_only = sorted(requested & ADMIN_ONLY_KEYS)
    if admin_only:
        raise _invalid(
            "User Management and Roles & Permissions are reserved for the Company Admin.",
            "permission_not_assignable",
        )
    return requested | BASELINE


def _name_taken(db: Session, name: str, exclude: uuid.UUID | None = None) -> bool:
    stmt = select(CompanyRole.id).where(func.lower(CompanyRole.name) == name.lower())
    if exclude is not None:
        stmt = stmt.where(CompanyRole.id != exclude)
    return db.scalar(stmt) is not None


def _taken() -> AppError:
    return AppError(409, "role_name_taken", "A role with this name already exists.")


def _audit(db: Session, actor: User, action: str, details: dict[str, object]) -> None:
    db.add(AuditEvent(action=action, actor=f"user:{actor.id}", details=details))


def create_role(
    db: Session, *, actor: User, name: str, description: str | None, permissions: list[str]
) -> RoleView:
    clean_name = _clean_name(name)
    clean_description = _clean_description(description)
    keys = _clean_permissions(permissions)
    try:
        if _name_taken(db, clean_name):
            raise _taken()
        role = CompanyRole(
            name=clean_name,
            description=clean_description,
            is_active=True,
            version=1,
            created_by_user_id=actor.id,
            updated_by_user_id=actor.id,
        )
        role.permissions = [CompanyRolePermission(permission=k) for k in sorted(keys)]
        db.add(role)
        db.flush()
        _audit(
            db,
            actor,
            "company_role.created",
            {"role_id": str(role.id), "name": role.name, "permissions": sorted(keys)},
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _taken() from None
    except Exception:
        db.rollback()
        raise
    return get_role_view(db, role.id)


def _locked_custom_role(db: Session, role_id: uuid.UUID) -> CompanyRole:
    role = db.scalar(select(CompanyRole).where(CompanyRole.id == role_id).with_for_update())
    if role is None:
        raise _not_found()
    if role.is_system:
        raise _protected()
    return role


def update_role(
    db: Session,
    *,
    actor: User,
    role_id: uuid.UUID,
    expected_version: int,
    name: str | None,
    description: str | None,
    permissions: list[str] | None,
    description_set: bool,
) -> RoleView:
    try:
        role = _locked_custom_role(db, role_id)
        if role.version != expected_version:
            raise AppError(
                409,
                "stale_role",
                "This role was changed after the page was opened. Reload and try again.",
            )
        if not role.is_active:
            raise AppError(409, "role_inactive", "Retired roles cannot be edited.")
        changed: list[str] = []
        if name is not None:
            clean_name = _clean_name(name)
            if clean_name != role.name:
                if _name_taken(db, clean_name, exclude=role.id):
                    raise _taken()
                role.name = clean_name
                changed.append("name")
        if description_set:
            clean_description = _clean_description(description)
            if clean_description != role.description:
                role.description = clean_description
                changed.append("description")
        added: list[str] = []
        removed: list[str] = []
        if permissions is not None:
            keys = _clean_permissions(permissions)
            current = role.permission_keys
            added, removed = sorted(keys - current), sorted(current - keys)
            if added or removed:
                role.permissions = [p for p in role.permissions if p.permission in keys] + [
                    CompanyRolePermission(permission=k) for k in added
                ]
        if not changed and not added and not removed:
            db.rollback()
            return get_role_view(db, role_id)
        role.version += 1
        role.updated_by_user_id = actor.id
        if changed:
            _audit(
                db,
                actor,
                "company_role.updated",
                {"role_id": str(role.id), "changed": changed, "name": role.name},
            )
        if added or removed:
            _audit(
                db,
                actor,
                "company_role.permissions_changed",
                {"role_id": str(role.id), "name": role.name, "added": added, "removed": removed},
            )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _taken() from None
    except Exception:
        db.rollback()
        raise
    return get_role_view(db, role_id)


def retire_role(
    db: Session,
    *,
    actor: User,
    role_id: uuid.UUID,
    expected_version: int,
    reassign_to: uuid.UUID | None,
) -> RoleView:
    try:
        role = _locked_custom_role(db, role_id)
        if role.version != expected_version:
            raise AppError(
                409,
                "stale_role",
                "This role was changed after the page was opened. Reload and try again.",
            )
        if not role.is_active:
            db.rollback()
            return get_role_view(db, role_id)
        assigned = (
            db.scalar(select(func.count()).select_from(User).where(User.company_role_id == role.id))
            or 0
        )
        target: CompanyRole | None = None
        if assigned:
            if reassign_to is None:
                raise AppError(
                    409,
                    "role_in_use",
                    f"This role is assigned to {assigned} user(s). Choose a role to move them "
                    "to before retiring it.",
                )
            target = db.get(CompanyRole, reassign_to)
            if (
                target is None
                or target.id == role.id
                or not target.is_active
                or target.system_key == SYSTEM_COMPANY_ADMIN
            ):
                raise AppError(422, "invalid_role", "Choose an active role to move the users to.")
            db.execute(
                update(User)
                .where(
                    User.company_role_id == role.id,
                    User.access_category == AccessCategory.COMPANY_USER,
                )
                .values(company_role_id=target.id)
            )
        role.is_active = False
        role.version += 1
        role.updated_by_user_id = actor.id
        _audit(
            db,
            actor,
            "company_role.retired",
            {
                "role_id": str(role.id),
                "name": role.name,
                "reassigned_users": int(assigned),
                "reassigned_to": target.name if target else None,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    logger.info("company role retired by %s", actor.id, extra={"role_id": str(role_id)})
    return get_role_view(db, role_id)
