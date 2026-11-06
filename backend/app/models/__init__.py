"""ORM models. Import every model here so Alembic sees it on Base.metadata."""

from app.models.app_subscription import AppSubscription
from app.models.audit_event import AuditEvent
from app.models.auth_session import AuthenticationSession
from app.models.company_roles import CompanyRole, CompanyRolePermission, PasswordSetupToken
from app.models.email_settings import EmailSettings
from app.models.reminders import EmailDeliveryAttempt, EmailOutbox, SubscriptionReminderSettings
from app.models.shop import Shop
from app.models.shop_access import UserShopAccess, UserShopAssignment
from app.models.shop_allowance import ShopAllowance
from app.models.subscription_renewal import SubscriptionRenewal
from app.models.user import AccessCategory, User

__all__ = [
    "AccessCategory",
    "AppSubscription",
    "AuditEvent",
    "AuthenticationSession",
    "CompanyRole",
    "CompanyRolePermission",
    "EmailDeliveryAttempt",
    "EmailOutbox",
    "EmailSettings",
    "PasswordSetupToken",
    "Shop",
    "ShopAllowance",
    "SubscriptionReminderSettings",
    "SubscriptionRenewal",
    "User",
    "UserShopAccess",
    "UserShopAssignment",
]
