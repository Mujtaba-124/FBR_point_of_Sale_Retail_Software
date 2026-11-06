"""Authentication and authorization dependencies.

Every protected endpoint must depend on one of the ``require_*`` guards. Roles
always come from the database row behind the session, never from the client.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, PermissionDenied
from app.core.security import tokens_match
from app.db.session import get_db
from app.models import AccessCategory, AuthenticationSession, User
from app.services.sessions import require_session
from app.services.subscription_access import ensure_company_access

DbSession = Annotated[Session, Depends(get_db)]

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _csrf_failed() -> AppError:
    return AppError(403, "csrf_failed", "The request could not be verified. Refresh and try again.")


def verify_origin(request: Request) -> None:
    """Reject state-changing requests sent from a foreign browser origin.

    Browsers always send Origin on cross-origin POSTs; non-browser clients may
    omit it, which is acceptable because they cannot ride a victim's cookies.
    """
    if request.method in _SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is not None and origin not in get_settings().cors_origin_list:
        raise _csrf_failed()


def current_session(request: Request, db: DbSession) -> AuthenticationSession:
    auth_session = require_session(db, request)
    if request.method not in _SAFE_METHODS:
        verify_origin(request)
        header = request.headers.get("x-csrf-token")
        if not header or not tokens_match(header, auth_session.csrf_token_hash):
            raise _csrf_failed()
    return auth_session


CurrentSession = Annotated[AuthenticationSession, Depends(current_session)]


def current_user(auth_session: CurrentSession) -> User:
    return auth_session.user


def require_categories(*allowed: AccessCategory) -> Callable[..., User]:
    allowed_set = frozenset(allowed)

    def guard(auth_session: CurrentSession) -> User:
        user = auth_session.user
        if user.access_category not in allowed_set:
            raise PermissionDenied()
        return user

    return guard


def require_valid_company_subscription(db: DbSession) -> None:
    """Deny Company Workspace operations unless the subscription is valid right now.

    Evaluated on every request from the database and the server clock, so an
    existing session loses access the moment the expiry boundary passes.
    FastAPI caches this per request, so stacked Company guards query it once.
    """
    ensure_company_access(db)


ValidCompanySubscription = Depends(require_valid_company_subscription)


def require_company_categories(*allowed: AccessCategory) -> Callable[..., User]:
    """Company Workspace guard: role first (403 permission_denied), then subscription."""
    role_guard = require_categories(*allowed)

    def guard(
        user: Annotated[User, Depends(role_guard)],
        _subscription: Annotated[None, ValidCompanySubscription],
    ) -> User:
        return user

    return guard


# The Super Admin guard never checks the subscription: renewal must stay reachable.
require_super_admin = require_categories(AccessCategory.SUPER_ADMIN)
require_company_member = require_company_categories(
    AccessCategory.COMPANY_ADMIN, AccessCategory.COMPANY_USER
)
require_company_admin = require_company_categories(AccessCategory.COMPANY_ADMIN)


def require_company_permission(permission: str) -> Callable[..., User]:
    """Company Workspace guard for one capability, evaluated from the database on
    every request (role changes and revocations apply immediately). Unknown
    capabilities are always denied."""
    from app.services.permissions import has_permission

    def guard(user: Annotated[User, Depends(require_company_member)], db: DbSession) -> User:
        if not has_permission(db, user, permission):
            raise PermissionDenied()
        return user

    return guard


AuthenticatedUser = Annotated[User, Depends(current_user)]
SuperAdmin = Annotated[User, Depends(require_super_admin)]
CompanyMember = Annotated[User, Depends(require_company_member)]
CompanyAdmin = Annotated[User, Depends(require_company_admin)]
