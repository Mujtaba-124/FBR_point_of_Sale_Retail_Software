"""Workspace endpoints. Each is reachable only by its own access categories."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    CompanyAdmin,
    CompanyMember,
    DbSession,
    SuperAdmin,
    require_company_member,
)
from app.schemas.auth import CurrentUser, WorkspaceResponse
from app.schemas.company_dashboard import CompanyDashboardOut
from app.schemas.shop_context import ShopContextOut
from app.schemas.super_admin import SuperAdminDashboardOut
from app.services import shop_context
from app.services.company_dashboard import get_company_dashboard
from app.services.permissions import effective_permissions
from app.services.super_admin_dashboard import get_dashboard

super_admin_router = APIRouter(prefix="/super-admin", tags=["super-admin"])

# Router-level guard: EVERY route registered under /company (now and in future
# modules) requires a Company account AND a valid subscription, even if a route
# forgets its own guard. Route-level guards may narrow the role further.
company_router = APIRouter(
    prefix="/company", tags=["company"], dependencies=[Depends(require_company_member)]
)


@super_admin_router.get("/workspace", response_model=WorkspaceResponse)
def super_admin_workspace(user: SuperAdmin) -> WorkspaceResponse:
    return WorkspaceResponse(workspace="super_admin", user=CurrentUser.from_user(user))


@super_admin_router.get("/dashboard", response_model=SuperAdminDashboardOut)
def super_admin_dashboard(_: SuperAdmin, db: DbSession) -> SuperAdminDashboardOut:
    """Subscription status and limited Company Admin contact. No business data."""
    return SuperAdminDashboardOut.from_data(get_dashboard(db))


@company_router.get("/workspace", response_model=WorkspaceResponse)
def company_workspace(user: CompanyMember, db: DbSession) -> WorkspaceResponse:
    """Identity plus effective capabilities (for navigation display only)."""
    return WorkspaceResponse(
        workspace="company",
        user=CurrentUser.from_user(user),
        permissions=sorted(effective_permissions(db, user)),
        shop_context_enabled=shop_context.can_use_shop_context(db, user),
    )


@company_router.get("/admin/workspace", response_model=WorkspaceResponse)
def company_admin_workspace(user: CompanyAdmin) -> WorkspaceResponse:
    """Company-admin-only area (future: users, roles, shops)."""
    return WorkspaceResponse(workspace="company", user=CurrentUser.from_user(user))


@company_router.get("/dashboard/summary", response_model=CompanyDashboardOut)
def company_dashboard_summary(
    user: CompanyAdmin,
    db: DbSession,
    shop_id: Annotated[str | None, Query(max_length=64)] = None,
) -> CompanyDashboardOut:
    """Company Admin only (plus the router's subscription guard). Real counts only;
    modules that are not built yet are reported as unavailable, never as zero.

    ``shop_id`` selects the shop context (validated by the backend: 422 invalid,
    404 unknown, 409 inactive). Administrative counts stay company-wide and are
    labelled so in ``metric_scopes``; only operational metrics follow the context.
    """
    context = shop_context.resolve(db, user, shop_id)
    return CompanyDashboardOut.from_data(
        get_company_dashboard(db, user, context), context=ShopContextOut.from_context(context)
    )
