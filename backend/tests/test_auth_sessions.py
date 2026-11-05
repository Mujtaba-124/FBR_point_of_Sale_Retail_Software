"""Session lifetime, logout/revocation, CSRF and rate limiting."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.routes.auth import get_login_rate_limiter
from app.core.config import get_settings
from app.core.redis import get_redis
from app.main import app
from app.models import AccessCategory, AuthenticationSession, User
from app.services.rate_limit import LoginRateLimiter
from tests.conftest import csrf_header, login

# Company accounts sign in here, which requires a valid subscription.
pytestmark = pytest.mark.usefixtures("valid_subscription")


def _logged_in(client, make_user, category=AccessCategory.COMPANY_ADMIN):
    email, password = make_user(category)
    assert login(client, email, password).status_code == 200
    return email


def test_me_returns_current_user(client, make_user):
    email = _logged_in(client, make_user)
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == email
    assert response.headers["cache-control"] == "no-store"


def test_absolute_expiry_ends_the_session(client, make_user, db: Session):
    _logged_in(client, make_user)
    db.execute(
        update(AuthenticationSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    db.commit()

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"
    # The stale cookie is cleared.
    assert any(
        "__Host-cheena_session=" in c and "max-age=0" in c.lower()
        for c in response.headers.get_list("set-cookie")
    )


def test_idle_timeout_ends_the_session(client, make_user, db: Session):
    _logged_in(client, make_user)
    idle = timedelta(minutes=get_settings().session_idle_ttl_minutes + 1)
    db.execute(update(AuthenticationSession).values(last_seen_at=datetime.now(UTC) - idle))
    db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_deactivating_a_user_ends_existing_sessions(client, make_user, db: Session):
    email = _logged_in(client, make_user)
    db.execute(update(User).where(User.email == email).values(is_active=False))
    db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_logout_revokes_session_and_clears_cookies(client, make_user, db: Session):
    _logged_in(client, make_user)
    stolen_token = client.cookies.get("__Host-cheena_session")

    response = client.post("/api/v1/auth/logout", headers=csrf_header(client))

    assert response.status_code == 204
    set_cookies = " ".join(response.headers.get_list("set-cookie")).lower()
    assert "__host-cheena_session=" in set_cookies and "max-age=0" in set_cookies
    assert db.scalar(select(AuthenticationSession.revoked_at)) is not None

    # Even a copy of the old token no longer works.
    client.cookies.set("__Host-cheena_session", stolen_token)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_logout_without_csrf_token_is_rejected(client, make_user):
    _logged_in(client, make_user)
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"
    assert client.get("/api/v1/auth/me").status_code == 200  # still signed in


def test_logout_with_wrong_csrf_token_is_rejected(client, make_user):
    _logged_in(client, make_user)
    response = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "forged"})
    assert response.status_code == 403
    assert client.get("/api/v1/auth/me").status_code == 200


def test_state_change_from_foreign_origin_is_rejected_even_with_token(client, make_user):
    _logged_in(client, make_user)
    headers = csrf_header(client) | {"Origin": "https://evil.example"}
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 403


def test_csrf_token_of_another_session_is_rejected(client, make_user):
    from fastapi.testclient import TestClient

    _logged_in(client, make_user)
    with TestClient(app, base_url="https://testserver") as other:
        email, password = make_user(AccessCategory.COMPANY_USER)
        login(other, email, password)
        other_token = other.cookies.get("__Host-cheena_csrf")
    response = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": other_token})
    assert response.status_code == 403


def test_logout_without_session_is_401(client):
    assert client.post("/api/v1/auth/logout").status_code == 401


def test_repeated_failures_lock_the_email_even_for_the_right_password(client, make_user):
    email, password = make_user(AccessCategory.COMPANY_ADMIN)
    for _ in range(get_settings().login_max_failures_per_email):
        assert login(client, email, password + "x").status_code == 401

    response = login(client, email, password)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert int(response.headers["retry-after"]) > 0


def test_successful_login_resets_the_failure_counter(client, make_user):
    email, password = make_user(AccessCategory.COMPANY_ADMIN)
    limit = get_settings().login_max_failures_per_email
    for _ in range(limit - 1):
        login(client, email, password + "x")
    assert login(client, email, password).status_code == 200
    for _ in range(limit - 1):
        login(client, email, password + "x")
    assert login(client, email, password).status_code == 200


def test_per_ip_attempt_limit(client, make_user):
    settings = get_settings().model_copy(update={"login_max_attempts_per_ip": 3})
    app.dependency_overrides[get_login_rate_limiter] = lambda: LoginRateLimiter(
        get_redis(), settings
    )
    email, password = make_user(AccessCategory.COMPANY_ADMIN)
    for i in range(3):
        assert login(client, f"user{i}@example.test", "whatever-pass").status_code == 401
    assert login(client, email, password).status_code == 429
