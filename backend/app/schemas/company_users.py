"""User Management and Roles & Permissions API models.

Never carries password hashes, session data or setup-token hashes. The raw
setup token appears only in the create / reissue responses, once.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.company_roles import RoleView
from app.services.company_users import Capacity, CreatedUser, UserView
from app.services.permissions import CAPABILITIES, MODULES
from app.services.shop_access import AccessDetail, AccessSummary, AssignedShop

UserStatus = Literal["active", "inactive"]
SortField = Literal["name", "email", "role", "status", "last_login", "created"]


class CapacityOut(BaseModel):
    active: int
    limit: int
    available: int
    inactive: int

    @classmethod
    def from_capacity(cls, c: Capacity) -> "CapacityOut":
        return cls(active=c.active, limit=c.limit, available=c.available, inactive=c.inactive)


class RoleRefOut(BaseModel):
    id: uuid.UUID
    name: str
    is_system: bool
    is_active: bool


AccessMode = Literal["none", "selected", "all"]
ScopeMode = Literal["company", "all", "selected", "none"]


class ShopAccessSummaryOut(BaseModel):
    """``company``: the protected Company Admin (all shops, not editable)."""

    mode: ScopeMode
    shop_count: int | None

    @classmethod
    def from_summary(cls, s: AccessSummary) -> "ShopAccessSummaryOut":
        return cls(mode=s.mode, shop_count=s.shop_count)  # type: ignore[arg-type]


class AssignedShopOut(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    status: UserStatus

    @classmethod
    def from_shop(cls, s: AssignedShop) -> "AssignedShopOut":
        return cls(
            id=s.id, name=s.name, code=s.code, status="active" if s.is_active else "inactive"
        )


class ShopAccessDetailOut(BaseModel):
    mode: ScopeMode
    shop_count: int | None
    shops: list[AssignedShopOut]
    editable: bool
    version: int | None
    updated_at: datetime | None

    @classmethod
    def from_detail(cls, d: AccessDetail) -> "ShopAccessDetailOut":
        s = d.summary
        return cls(
            mode=s.mode,  # type: ignore[arg-type]
            shop_count=s.shop_count,
            shops=[AssignedShopOut.from_shop(x) for x in d.shops],
            editable=s.mode != "company",
            version=s.version,
            updated_at=s.updated_at,
        )


class ShopAccessUpdateOut(BaseModel):
    access: ShopAccessDetailOut
    changed: bool


class ShopAccessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: AccessMode
    shop_ids: list[uuid.UUID] = Field(default_factory=list, max_length=5000)


class UpdateShopAccessRequest(ShopAccessRequest):
    expected_version: int = Field(ge=1)


class AssignableShopsOut(BaseModel):
    items: list[AssignedShopOut]
    total: int


class CompanyUserOut(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    tier: Literal["company_admin", "company_user"]
    is_protected: bool
    status: UserStatus
    role: RoleRefOut | None
    setup_pending: bool
    setup_link_expires_at: datetime | None
    last_login_at: datetime | None
    created_at: datetime
    shop_access: ShopAccessSummaryOut

    @classmethod
    def from_view(cls, v: UserView) -> "CompanyUserOut":
        u = v.user
        return cls(
            id=u.id,
            full_name=u.full_name,
            email=u.email,
            tier=u.access_category.value,  # type: ignore[arg-type]
            is_protected=v.is_protected,
            status="active" if u.is_active else "inactive",
            role=RoleRefOut(
                id=v.role.id,
                name=v.role.name,
                is_system=v.role.is_system,
                is_active=v.role.is_active,
            )
            if v.role
            else None,
            setup_pending=u.must_set_password,
            setup_link_expires_at=v.setup_link_expires_at,
            last_login_at=u.last_login_at,
            created_at=u.created_at,
            shop_access=ShopAccessSummaryOut.from_summary(v.shop_access),
        )


class UserPageOut(BaseModel):
    items: list[CompanyUserOut]
    total: int
    limit: int
    offset: int
    capacity: CapacityOut


class CreateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=400)
    email: str = Field(min_length=3, max_length=320)
    role_id: uuid.UUID
    # Omitted: No Shop Access (the safe default).
    shop_access: ShopAccessRequest | None = None


class UpdateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=400)
    role_id: uuid.UUID | None = None


class SetupLinkIssuedOut(BaseModel):
    """The raw token is shown once; build the link as /set-password#token=<token>."""

    user: CompanyUserOut
    setup_token: str
    setup_expires_at: datetime
    capacity: CapacityOut

    @classmethod
    def build(cls, created: CreatedUser, capacity: Capacity) -> "SetupLinkIssuedOut":
        return cls(
            user=CompanyUserOut.from_view(created.view),
            setup_token=created.setup_token,
            setup_expires_at=created.setup_expires_at,
            capacity=CapacityOut.from_capacity(capacity),
        )


class UserActionOut(BaseModel):
    user: CompanyUserOut
    capacity: CapacityOut


# --- Roles ---------------------------------------------------------------------


class RoleOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    system_key: Literal["company_admin", "company_user"] | None
    is_system: bool
    is_active: bool
    permissions: list[str]
    active_users: int
    total_users: int
    version: int
    updated_at: datetime

    @classmethod
    def from_view(cls, v: RoleView) -> "RoleOut":
        r = v.role
        return cls(
            id=r.id,
            name=r.name,
            description=r.description,
            system_key=r.system_key,  # type: ignore[arg-type]
            is_system=r.is_system,
            is_active=r.is_active,
            permissions=v.permissions,
            active_users=v.active_users,
            total_users=v.total_users,
            version=r.version,
            updated_at=r.updated_at,
        )


class RoleListOut(BaseModel):
    items: list[RoleOut]


class CreateRoleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=600)
    permissions: list[str] = Field(default_factory=list, max_length=100)


class UpdateRoleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=600)
    permissions: list[str] | None = Field(default=None, max_length=100)


class RetireRoleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    reassign_to_role_id: uuid.UUID | None = None


class CapabilityOut(BaseModel):
    key: str
    label: str
    column: Literal["view", "create", "edit", "delete", "special"]


class ModuleOut(BaseModel):
    key: str
    label: str
    available: bool
    admin_only: bool
    capabilities: list[CapabilityOut]


class PermissionCatalogOut(BaseModel):
    modules: list[ModuleOut]
    baseline: list[str]

    @classmethod
    def build(cls) -> "PermissionCatalogOut":
        return cls(
            modules=[
                ModuleOut(
                    key=m.key,
                    label=m.label,
                    available=m.available,
                    admin_only=m.admin_only,
                    capabilities=[
                        CapabilityOut(key=c.key, label=c.label, column=c.column)  # type: ignore[arg-type]
                        for c in CAPABILITIES
                        if c.module == m.key
                    ],
                )
                for m in MODULES
            ],
            baseline=["dashboard.view"],
        )
