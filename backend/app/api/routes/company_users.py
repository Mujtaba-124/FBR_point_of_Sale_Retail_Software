"""Company Admin: User Management and Roles & Permissions.

Every route: Company account + valid subscription (router guard), then the
specific capability (route guard). The capabilities used here exist only on
the protected Company Admin tier, so Company Users and the Super Admin get 403.
State changes are CSRF-protected by ``current_session``.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession, require_company_member, require_company_permission
from app.models import User
from app.schemas.company_users import (
    AssignableShopsOut,
    AssignedShopOut,
    CapacityOut,
    CompanyUserOut,
    CreateRoleRequest,
    CreateUserRequest,
    PermissionCatalogOut,
    RetireRoleRequest,
    RoleListOut,
    RoleOut,
    SetupLinkIssuedOut,
    ShopAccessDetailOut,
    ShopAccessUpdateOut,
    SortField,
    UpdateRoleRequest,
    UpdateShopAccessRequest,
    UpdateUserRequest,
    UserActionOut,
    UserPageOut,
    UserStatus,
)
from app.services import company_roles as roles_svc
from app.services import company_users as users_svc
from app.services import shop_access as access_svc

router = APIRouter(
    prefix="/company", tags=["company"], dependencies=[Depends(require_company_member)]
)

UsersViewer = Annotated[User, Depends(require_company_permission("users.view"))]
UsersCreator = Annotated[User, Depends(require_company_permission("users.create"))]
UsersEditor = Annotated[User, Depends(require_company_permission("users.edit"))]
UsersActivator = Annotated[User, Depends(require_company_permission("users.deactivate"))]
RolesViewer = Annotated[User, Depends(require_company_permission("roles.view"))]
RolesManager = Annotated[User, Depends(require_company_permission("roles.manage"))]


def _capacity(db: DbSession) -> CapacityOut:
    return CapacityOut.from_capacity(users_svc.capacity(db))


# --- Users ------------------------------------------------------------------------


@router.get("/users", response_model=UserPageOut)
def list_users(
    _: UsersViewer,
    db: DbSession,
    search: Annotated[str | None, Query(max_length=100)] = None,
    status_filter: Annotated[UserStatus | None, Query(alias="status")] = None,
    role_id: uuid.UUID | None = None,
    sort: SortField = "name",
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> UserPageOut:
    views, total = users_svc.list_users(
        db,
        search=search,
        status=status_filter,
        role_id=role_id,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
    )
    return UserPageOut(
        items=[CompanyUserOut.from_view(v) for v in views],
        total=total,
        limit=limit,
        offset=offset,
        capacity=_capacity(db),
    )


@router.post("/users", response_model=SetupLinkIssuedOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: CreateUserRequest, user: UsersCreator, db: DbSession
) -> SetupLinkIssuedOut:
    access = payload.shop_access
    created = users_svc.create_user(
        db,
        actor=user,
        full_name=payload.full_name,
        email=payload.email,
        role_id=payload.role_id,
        access_mode=access.mode if access else "none",
        shop_ids=access.shop_ids if access else [],
    )
    return SetupLinkIssuedOut.build(created, users_svc.capacity(db))


@router.get("/shop-assignment-options", response_model=AssignableShopsOut)
def shop_assignment_options(_: UsersEditor, db: DbSession) -> AssignableShopsOut:
    """Every registered shop (ID, name, code, status) for the Shop Access checklist."""
    shops = access_svc.assignable_shops(db)
    return AssignableShopsOut(items=[AssignedShopOut.from_shop(s) for s in shops], total=len(shops))


@router.get("/users/{user_id}/shop-access", response_model=ShopAccessDetailOut)
def get_shop_access(user_id: uuid.UUID, _: UsersViewer, db: DbSession) -> ShopAccessDetailOut:
    return ShopAccessDetailOut.from_detail(
        access_svc.detail_for(db, users_svc.get_company_user(db, user_id))
    )


@router.put("/users/{user_id}/shop-access", response_model=ShopAccessUpdateOut)
def set_shop_access(
    user_id: uuid.UUID, payload: UpdateShopAccessRequest, user: UsersEditor, db: DbSession
) -> ShopAccessUpdateOut:
    """Replace one Company User's shop access (CSRF-protected, versioned, audited)."""
    try:
        target = users_svc.get_company_user(db, user_id, lock=True)  # serializes saves
    except Exception:
        db.rollback()
        raise
    detail, changed = access_svc.set_access(
        db,
        actor=user,
        target=target,
        mode=payload.mode,
        shop_ids=payload.shop_ids,
        expected_version=payload.expected_version,
    )
    return ShopAccessUpdateOut(access=ShopAccessDetailOut.from_detail(detail), changed=changed)


@router.get("/users/{user_id}", response_model=CompanyUserOut)
def get_user(user_id: uuid.UUID, _: UsersViewer, db: DbSession) -> CompanyUserOut:
    return CompanyUserOut.from_view(users_svc.get_user_view(db, user_id))


@router.patch("/users/{user_id}", response_model=CompanyUserOut)
def update_user(
    user_id: uuid.UUID, payload: UpdateUserRequest, user: UsersEditor, db: DbSession
) -> CompanyUserOut:
    view = users_svc.update_user(
        db, actor=user, user_id=user_id, full_name=payload.full_name, role_id=payload.role_id
    )
    return CompanyUserOut.from_view(view)


@router.post("/users/{user_id}/deactivate", response_model=UserActionOut)
def deactivate_user(user_id: uuid.UUID, user: UsersActivator, db: DbSession) -> UserActionOut:
    view = users_svc.deactivate_user(db, actor=user, user_id=user_id)
    return UserActionOut(user=CompanyUserOut.from_view(view), capacity=_capacity(db))


@router.post("/users/{user_id}/reactivate", response_model=UserActionOut)
def reactivate_user(user_id: uuid.UUID, user: UsersActivator, db: DbSession) -> UserActionOut:
    view = users_svc.reactivate_user(db, actor=user, user_id=user_id)
    return UserActionOut(user=CompanyUserOut.from_view(view), capacity=_capacity(db))


@router.post("/users/{user_id}/setup-link", response_model=SetupLinkIssuedOut)
def reissue_setup_link(user_id: uuid.UUID, user: UsersCreator, db: DbSession) -> SetupLinkIssuedOut:
    created = users_svc.reissue_setup_link(db, actor=user, user_id=user_id)
    return SetupLinkIssuedOut.build(created, users_svc.capacity(db))


# --- Roles & permissions ----------------------------------------------------------


@router.get("/permissions", response_model=PermissionCatalogOut)
def permission_catalog(_: RolesViewer) -> PermissionCatalogOut:
    return PermissionCatalogOut.build()


@router.get("/roles", response_model=RoleListOut)
def list_roles(_: RolesViewer, db: DbSession) -> RoleListOut:
    return RoleListOut(items=[RoleOut.from_view(v) for v in roles_svc.list_roles(db)])


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
def create_role(payload: CreateRoleRequest, user: RolesManager, db: DbSession) -> RoleOut:
    view = roles_svc.create_role(
        db,
        actor=user,
        name=payload.name,
        description=payload.description,
        permissions=payload.permissions,
    )
    return RoleOut.from_view(view)


@router.patch("/roles/{role_id}", response_model=RoleOut)
def update_role(
    role_id: uuid.UUID, payload: UpdateRoleRequest, user: RolesManager, db: DbSession
) -> RoleOut:
    view = roles_svc.update_role(
        db,
        actor=user,
        role_id=role_id,
        expected_version=payload.expected_version,
        name=payload.name,
        description=payload.description,
        description_set="description" in payload.model_fields_set,
        permissions=payload.permissions,
    )
    return RoleOut.from_view(view)


@router.post("/roles/{role_id}/retire", response_model=RoleOut)
def retire_role(
    role_id: uuid.UUID, payload: RetireRoleRequest, user: RolesManager, db: DbSession
) -> RoleOut:
    view = roles_svc.retire_role(
        db,
        actor=user,
        role_id=role_id,
        expected_version=payload.expected_version,
        reassign_to=payload.reassign_to_role_id,
    )
    return RoleOut.from_view(view)
