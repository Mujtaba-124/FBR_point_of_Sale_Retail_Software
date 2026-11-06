"""Leftover cookies from the other COOKIE_SECURE mode are removed on login and logout.

Regression: a browser that once received "__Host-cheena_*" cookies (secure mode)
kept them after the backend switched to plain "cheena_*" cookies for local HTTP.
The client then sent the stale CSRF token and every write failed with
csrf_failed ("The request could not be verified"), including Sign out.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.models import AccessCategory
from tests.conftest import csrf_header, login

ORIGIN = {"Origin": "http://localhost:3000"}
pytestmark = pytest.mark.usefixtures("valid_subscription")


def expired(set_cookies: list[str], name: str) -> bool:
    return any(c.startswith(f"{name}=") and "Max-Age=0" in c for c in set_cookies)


def test_inactive_mode_names_are_the_other_family() -> None:
    settings = get_settings()
    assert settings.cookie_secure is True  # the test suite runs in secure mode
    assert settings.inactive_cookie_names == ("cheena_session", "cheena_csrf")
    assert settings.session_cookie_name not in settings.inactive_cookie_names
    assert settings.csrf_cookie_name not in settings.inactive_cookie_names


def test_login_expires_leftover_cookies_of_the_other_mode(client: TestClient, make_user) -> None:
    email, password = make_user(AccessCategory.COMPANY_ADMIN)
    res = login(client, email, password)
    assert res.status_code == 200
    cookies = res.headers.get_list("set-cookie")
    assert expired(cookies, "cheena_session") and expired(cookies, "cheena_csrf")
    # The active pair is issued normally and works for a state-changing request.
    assert any(c.startswith("__Host-cheena_csrf=") and "Max-Age=0" not in c for c in cookies)
    out = client.post("/api/v1/auth/logout", headers={**csrf_header(client), **ORIGIN})
    assert out.status_code == 204


def test_logout_expires_both_cookie_families(client: TestClient, make_user) -> None:
    email, password = make_user(AccessCategory.SUPER_ADMIN)
    assert login(client, email, password).status_code == 200
    res = client.post("/api/v1/auth/logout", headers={**csrf_header(client), **ORIGIN})
    assert res.status_code == 204
    cookies = res.headers.get_list("set-cookie")
    for name in ("__Host-cheena_session", "__Host-cheena_csrf", "cheena_session", "cheena_csrf"):
        assert expired(cookies, name), name
    # "__Host-" cookies can only be removed by a Secure Set-Cookie with Path=/.
    host = [c for c in cookies if c.startswith("__Host-")]
    assert all("Secure" in c and "Path=/" in c for c in host)


def test_a_stale_token_alone_is_still_rejected(client: TestClient, make_user) -> None:
    """The fix cleans cookies up; it never relaxes the CSRF check."""
    email, password = make_user(AccessCategory.COMPANY_ADMIN)
    assert login(client, email, password).status_code == 200
    res = client.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": "stale-token-from-old-mode", **ORIGIN}
    )
    assert res.status_code == 403 and res.json()["error"]["code"] == "csrf_failed"
