from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import AuthenticatedUser, CurrentSession, DbSession, verify_origin
from app.core.config import get_settings
from app.core.redis import get_redis
from app.models import AccessCategory
from app.schemas.auth import (
    CompanyAccessOut,
    CurrentUser,
    LoginRequest,
    LoginResponse,
    MeResponse,
)
from app.services import auth_service
from app.services.rate_limit import LoginRateLimiter
from app.services.sessions import clear_auth_cookies, client_ip, revoke_session, set_auth_cookies
from app.services.subscription_access import company_access

router = APIRouter(prefix="/auth", tags=["auth"])


def get_login_rate_limiter() -> LoginRateLimiter:
    return LoginRateLimiter(get_redis(), get_settings())


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
    limiter: Annotated[LoginRateLimiter, Depends(get_login_rate_limiter)],
) -> LoginResponse:
    """Verify credentials and start a session (cookie-based)."""
    verify_origin(request)
    user, issued = auth_service.login(
        db, request, limiter, payload.email, payload.password, client_ip(request)
    )
    set_auth_cookies(response, issued)
    return LoginResponse(user=CurrentUser.from_user(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(auth_session: CurrentSession, db: DbSession) -> Response:
    """Revoke the current session and clear its cookies. Requires the CSRF header."""
    revoke_session(db, auth_session)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_auth_cookies(response)
    return response


@router.get("/me", response_model=MeResponse)
def me(user: AuthenticatedUser, db: DbSession) -> MeResponse:
    """Identity of the session. Works even when Company access is blocked by the
    subscription, so the frontend can show the restricted state and sign out."""
    base = CurrentUser.from_user(user)
    company = None
    if user.access_category != AccessCategory.SUPER_ADMIN:
        access = company_access(db)
        company = CompanyAccessOut(allowed=access.allowed, code=access.code)
    return MeResponse(**base.model_dump(), company_access=company)
