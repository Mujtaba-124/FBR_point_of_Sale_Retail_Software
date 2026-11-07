"""Company Workspace capability catalog and effective-permission evaluation.

Rules (enforced server-side on every request; the sidebar only mirrors them):
- Only keys in this catalog exist. Anything else is denied and cannot be stored.
- Company Admin (protected tier) holds every capability, from its access tier,
  never from an editable role.
- Company User capabilities come from their assigned role, if that role is
  active. ``dashboard.view`` is the baseline every active Company account has.
- ``admin_only`` capabilities (User Management, Roles & Permissions) can never
  be granted to a role, so no Company User can reach those areas.
- Super Admin holds no Company capability at all.
- Modules marked ``available=False`` are not built yet: their capabilities can
  be prepared on a role but grant nothing usable (no routes or APIs exist).
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import AccessCategory, CompanyRole, User


@dataclass(frozen=True)
class Module:
    key: str
    label: str
    available: bool
    admin_only: bool = False


@dataclass(frozen=True)
class Capability:
    key: str
    module: str
    label: str
    column: str  # view | create | edit | delete | special (permission matrix layout)


MODULES: tuple[Module, ...] = (
    Module("dashboard", "Dashboard", available=True),
    Module("users", "User Management", available=True, admin_only=True),
    Module("roles", "Roles & Permissions", available=True, admin_only=True),
    Module("shops", "Shops", available=True),
    Module("uploads", "Excel Uploads", available=True),
    Module("approvals", "Approvals", available=False),
    Module("fbr_sync", "FBR Sync", available=False),
    Module("reports", "Reports", available=False),
)

CAPABILITIES: tuple[Capability, ...] = (
    Capability("dashboard.view", "dashboard", "View", "view"),
    Capability("users.view", "users", "View", "view"),
    Capability("users.create", "users", "Create", "create"),
    Capability("users.edit", "users", "Edit", "edit"),
    Capability("users.deactivate", "users", "Activate / Deactivate", "special"),
    Capability("roles.view", "roles", "View", "view"),
    Capability("roles.manage", "roles", "Create / edit / retire roles", "edit"),
    Capability("shops.view", "shops", "View", "view"),
    Capability("shops.create", "shops", "Create", "create"),
    Capability("shops.edit", "shops", "Edit", "edit"),
    # No permanent deletion exists: "delete" maps to deactivate / reactivate.
    Capability("shops.delete", "shops", "Deactivate / Reactivate", "delete"),
    Capability("shops.manage_integration", "shops", "Manage FBR token", "special"),
    Capability("uploads.view", "uploads", "View", "view"),
    Capability("uploads.upload", "uploads", "Upload", "create"),
    Capability("uploads.edit_draft", "uploads", "Replace draft", "edit"),
    Capability("uploads.delete_draft", "uploads", "Delete draft (not available yet)", "delete"),
    Capability("uploads.submit", "uploads", "Submit for approval (with Approvals)", "special"),
    Capability("approvals.view", "approvals", "View", "view"),
    Capability("approvals.decide", "approvals", "Accept / Reject", "special"),
    Capability("fbr_sync.view", "fbr_sync", "View", "view"),
    Capability("fbr_sync.control", "fbr_sync", "Start / Stop / Cancel / Resume", "special"),
    Capability("fbr_sync.retry", "fbr_sync", "Retry", "special"),
    Capability("reports.view", "reports", "View", "view"),
    Capability("reports.export", "reports", "Export", "special"),
)

BASELINE = frozenset({"dashboard.view"})
_MODULES = {m.key: m for m in MODULES}
ALL_KEYS = frozenset(c.key for c in CAPABILITIES)
ADMIN_ONLY_KEYS = frozenset(c.key for c in CAPABILITIES if _MODULES[c.module].admin_only)
ASSIGNABLE_KEYS = ALL_KEYS - ADMIN_ONLY_KEYS


def module_of(key: str) -> Module:
    return _MODULES[key.split(".", 1)[0]]


def is_usable(key: str) -> bool:
    """A capability does something only if its module exists."""
    return key in ALL_KEYS and module_of(key).available


def role_capabilities(role: CompanyRole | None) -> frozenset[str]:
    if role is None or not role.is_active:
        return BASELINE
    return BASELINE | (role.permission_keys & ASSIGNABLE_KEYS)


def effective_permissions(db: Session, user: User) -> frozenset[str]:
    """Authoritative capabilities of a signed-in user, read from the database."""
    if not user.is_active:
        return frozenset()
    if user.access_category == AccessCategory.COMPANY_ADMIN:
        return ALL_KEYS
    if user.access_category == AccessCategory.COMPANY_USER:
        role = db.get(CompanyRole, user.company_role_id) if user.company_role_id else None
        return role_capabilities(role)
    return frozenset()  # Super Admin: no Company capabilities


def has_permission(db: Session, user: User, key: str) -> bool:
    return key in ALL_KEYS and key in effective_permissions(db, user)
