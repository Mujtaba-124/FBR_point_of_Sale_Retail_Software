from fastapi import APIRouter

from app.api.routes import auth, email_settings, health, reminders, subscription, workspaces

api_router = APIRouter()
api_router.include_router(health.router)

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(auth.router)
v1_router.include_router(workspaces.super_admin_router)
v1_router.include_router(subscription.router)
v1_router.include_router(email_settings.router)
v1_router.include_router(reminders.router)
v1_router.include_router(workspaces.company_router)
api_router.include_router(v1_router)
