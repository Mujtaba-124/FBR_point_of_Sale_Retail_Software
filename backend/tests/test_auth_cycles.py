"""Backend side of repeated login/logout cycles (the reported bug's server contract).

The bug itself was in the frontend, but these pin down what the backend must
guarantee for login to work right after logout: fresh session and CSRF token
every time, the old ones dead, and no leftovers blocking the next login.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import AccessCategory, AuthenticationSession
from tests.conftest import csrf_header, login

# Company accounts sign in here, which requires a valid subscription.
pytestmark = pytest.mark.usefixtures("valid_subscription")

SESSION = "__Host-cheena_session"
CSRF = "__Host-cheena_csrf"
WORKSPACE = {
    AccessCategory.SUPER_ADMIN: ("/api/v1/super-admin/workspace", "/api/v1/company/workspace"),
    AccessCategory.COMPANY_ADMIN: ("/api/v1/company/workspace", "/api/v1/super-admin/workspace"),
}


@pytest.mark.parametrize("category", list(WORKSPACE))
def test_five_login_logout_cycles_in_the_same_browser(client, db: Session, make_user, category):
    email, password = make_user(category)
    own, other = WORKSPACE[category]
    seen_sessions, seen_csrf = set(), set()

    for _ in range(5):
        assert login(client, email, password).status_code == 200
        session_token, csrf_token = client.cookies.get(SESSION), client.cookies.get(CSRF)
        assert session_token not in seen_sessions and csrf_token not in seen_csrf
        seen_sessions.add(session_token)
        seen_csrf.add(csrf_token)

        assert client.get(own).status_code == 200
        assert client.get(other).status_code == 403

        assert client.post("/api/v1/auth/logout", headers=csrf_header(client)).status_code == 204
        assert client.get("/api/v1/auth/me").status_code == 401

    sessions = db.scalars(select(AuthenticationSession)).all()
    assert len(sessions) == 5
    assert all(s.revoked_at is not None for s in sessions)


def test_previous_sessions_csrf_token_is_rejected_after_relogin(client, make_user):
    email, password = make_user(AccessCategory.COMPANY_ADMIN)
    login(client, email, password)
    old_csrf = client.cookies.get(CSRF)
    client.post("/api/v1/auth/logout", headers=csrf_header(client))

    login(client, email, password)
    response = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": old_csrf})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"
    assert client.get("/api/v1/auth/me").status_code == 200  # still signed in


def test_login_works_while_stale_cookies_are_still_present(client, make_user):
    """Simulates a browser that kept cookies from a revoked session."""
    email, password = make_user(AccessCategory.SUPER_ADMIN)
    login(client, email, password)
    stale_session, stale_csrf = client.cookies.get(SESSION), client.cookies.get(CSRF)
    client.post("/api/v1/auth/logout", headers=csrf_header(client))
    client.cookies.clear()
    client.cookies.set(SESSION, stale_session)
    client.cookies.set(CSRF, stale_csrf)

    response = login(client, email, password)

    assert response.status_code == 200
    fresh_session = response.cookies.get(SESSION)
    assert fresh_session and fresh_session != stale_session
    client.cookies.clear()
    client.cookies.set(SESSION, fresh_session)
    assert client.get("/api/v1/super-admin/workspace").status_code == 200
    client.cookies.clear()
    client.cookies.set(SESSION, stale_session)
    assert client.get("/api/v1/auth/me").status_code == 401  # the stale one stays dead


def test_login_immediately_after_session_expiry(client, db: Session, make_user):
    email, password = make_user(AccessCategory.COMPANY_ADMIN)
    login(client, email, password)
    db.execute(
        update(AuthenticationSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401

    assert login(client, email, password).status_code == 200
    assert client.get("/api/v1/company/workspace").status_code == 200


def test_invalid_then_valid_credentials(client, make_user):
    email, password = make_user(AccessCategory.COMPANY_ADMIN)
    assert login(client, email, password + "x").status_code == 401
    assert login(client, email, password).status_code == 200
    assert client.get("/api/v1/company/workspace").status_code == 200
