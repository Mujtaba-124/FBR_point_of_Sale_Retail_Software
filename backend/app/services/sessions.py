"""Server-managed browser sessions.

A session is identified by an opaque 256-bit token held in an HttpOnly cookie.
PostgreSQL stores only the SHA-256 hash of the token, so a database leak does
not reveal usable session tokens. Each session also has a CSRF token: it is
readable by the frontend (non-HttpOnly cookie) and must be echoed back in the
``X-CSRF-Token`` header on state-changing requests; the server compares it
with the hash stored on the session.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Request, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import NotAuthenticated
from app.core.security import hash_token, new_token
from app.models import AuthenticationSession, User

# Avoid a database write on every request: refresh last_seen_at at most this often.
_LAST_SEEN_REFRESH = timedelta(seconds=60)


@dataclass(frozen=True)
class IssuedSession:
    session: AuthenticationSession
    token: str
    csrf_token: str


def _now() -> datetime:
    return datetime.now(UTC)


def client_ip(request: Request) -> str:
    settings = get_settings()
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()[:45]
    return (request.client.host if request.client else "unknown")[:45]


def create_session(db: Session, user: User, request: Request) -> IssuedSession:
    settings = get_settings()
    token, csrf_token = new_token(), new_token()
    now = _now()
    auth_session = AuthenticationSession(
        user_id=user.id,
        token_hash=hash_token(token),
        csrf_token_hash=hash_token(csrf_token),
        expires_at=now + timedelta(minutes=settings.session_absolute_ttl_minutes),
        last_seen_at=now,
        ip_address=client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:255] or None,
    )
    db.add(auth_session)
    return IssuedSession(session=auth_session, token=token, csrf_token=csrf_token)


def find_active_session(db: Session, token: str) -> AuthenticationSession | None:
    """Return the live session for a token, or None if unknown, revoked or expired."""
    settings = get_settings()
    auth_session = db.scalar(
        select(AuthenticationSession).where(AuthenticationSession.token_hash == hash_token(token))
    )
    if auth_session is None or auth_session.revoked_at is not None:
        return None

    now = _now()
    idle_limit = auth_session.last_seen_at + timedelta(minutes=settings.session_idle_ttl_minutes)
    if now >= auth_session.expires_at or now >= idle_limit:
        auth_session.revoked_at = now
        db.commit()
        return None
    if not auth_session.user.is_active:
        return None

    if now - auth_session.last_seen_at >= _LAST_SEEN_REFRESH:
        auth_session.last_seen_at = now
        db.commit()
    return auth_session


def require_session(db: Session, request: Request) -> AuthenticationSession:
    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        raise NotAuthenticated()
    auth_session = find_active_session(db, token)
    if auth_session is None:
        raise NotAuthenticated("Your session has expired. Please sign in again.")
    return auth_session


def revoke_session(db: Session, auth_session: AuthenticationSession) -> None:
    auth_session.revoked_at = _now()
    db.commit()


def revoke_token_if_present(db: Session, request: Request) -> None:
    """Revoke any session the browser already holds (new login = new session)."""
    token = request.cookies.get(get_settings().session_cookie_name)
    if token:
        db.execute(
            update(AuthenticationSession)
            .where(
                AuthenticationSession.token_hash == hash_token(token),
                AuthenticationSession.revoked_at.is_(None),
            )
            .values(revoked_at=_now())
        )


# --- Cookies ---------------------------------------------------------------


def set_auth_cookies(response: Response, issued: IssuedSession) -> None:
    settings = get_settings()
    # No Max-Age: a browser-session cookie. The server enforces absolute and
    # idle expiry regardless of what the browser keeps.
    response.set_cookie(
        settings.session_cookie_name,
        issued.token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        issued.csrf_token,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        settings.csrf_cookie_name,
        path="/",
        secure=settings.cookie_secure,
        httponly=False,
        samesite="strict",
    )


def request_has_session_cookie(request: Request) -> bool:
    return get_settings().session_cookie_name in request.cookies
