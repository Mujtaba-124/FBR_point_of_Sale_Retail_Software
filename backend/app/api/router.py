from fastapi import APIRouter

from app.api.routes import (
    auth,
    company_users,
    email_settings,
    health,
    reminders,
    shop_allowance,
    shop_context,
    shops,
    subscription,
    workspaces,
)

api_router = APIRouter()
api_router.include_router(health.router)

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(auth.router)
v1_router.include_router(workspaces.super_admin_router)
v1_router.include_router(subscription.router)
v1_router.include_router(shop_allowance.router)
v1_router.include_router(email_settings.router)
v1_router.include_router(reminders.router)
v1_router.include_router(workspaces.company_router)
v1_router.include_router(company_users.router)
v1_router.include_router(shops.router)
v1_router.include_router(shop_context.router)
api_router.include_router(v1_router)
