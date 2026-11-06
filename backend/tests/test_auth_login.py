"""Login, credentials, inactive accounts, hashing and cookie security."""

import logging

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import hash_password, verify_password
from app.models import AccessCategory, AuthenticationSession, User
from tests.conftest import login

# Company accounts sign in here, which requires a valid subscription.
pytestmark = pytest.mark.usefixtures("valid_subscription")


def _set_cookie_headers(response) -> list[str]:
    return response.headers.get_list("set-cookie")


def test_successful_login_returns_safe_profile_and_creates_session(client, make_user, db: Session):
    email, password = make_user(AccessCategory.COMPANY_ADMIN)

    response = login(client, email, password)

    assert response.status_code == 200
    user = response.json()["user"]
    assert user["email"] == email
    assert user["access_category"] == "company_admin"
    assert user["workspace"] == "company"
    assert set(user) == {"id", "email", "full_name", "access_category", "workspace"}
    assert "password" not in response.text and "hash" not in response.text

    token = client.cookies.get("__Host-cheena_session")
    stored = db.scalars(select(AuthenticationSession)).all()
    assert len(stored) == 1
    assert stored[0].token_hash != token  # only the hash is stored
    assert stored[0].revoked_at is None


def test_login_is_case_insensitive_for_email(client, make_user):
    email, password = make_user(AccessCategory.COMPANY_USER)
    assert login(client, email.upper(), password).status_code == 200


def test_invalid_credentials_do_not_reveal_which_part_was_wrong(client, make_user):
    email, password = make_user(AccessCategory.COMPANY_USER)

    wrong_password = login(client, email, password + "x")
    unknown_email = login(client, "nobody@example.test", password)

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert (
        wrong_password.json()
        == unknown_email.json()
        == {"error": {"code": "invalid_credentials", "message": "Invalid email or password."}}
    )
    assert not _set_cookie_headers(wrong_password)


def test_inactive_account_is_refused_without_a_session(client, make_user, db: Session):
    email, password = make_user(AccessCategory.COMPANY_ADMIN, active=False)

    response = login(client, email, password)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "account_inactive"
    assert not _set_cookie_headers(response)
    assert db.scalars(select(AuthenticationSession)).all() == []


def test_inactive_account_with_wrong_password_looks_like_bad_credentials(client, make_user):
    email, password = make_user(AccessCategory.COMPANY_ADMIN, active=False)
    response = login(client, email, password + "x")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_client_cannot_supply_its_own_role(client, make_user):
    email, password = make_user(AccessCategory.COMPANY_USER)
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "access_category": "super_admin"},
    )
    assert response.status_code == 422


def test_passwords_are_hashed_with_argon2id(make_user, db: Session):
    email, password = make_user(AccessCategory.SUPER_ADMIN)
    stored = db.scalar(select(User.password_hash).where(User.email == email))

    assert stored.startswith("$argon2id$")
    assert password not in stored
    assert verify_password(stored, password)
    assert not verify_password(stored, password + "x")
    assert hash_password(password) != hash_password(password)  # salted


def test_session_cookie_flags_in_secure_mode(client, make_user):
    email, password = make_user(AccessCategory.COMPANY_USER)
    response = login(client, email, password)
    cookies = {c.split("=", 1)[0]: c.lower() for c in _set_cookie_headers(response)}

    session_cookie = cookies["__Host-cheena_session"]
    assert "httponly" in session_cookie
    assert "secure" in session_cookie
    assert "samesite=lax" in session_cookie
    assert "path=/" in session_cookie
    assert "domain=" not in session_cookie
    assert "max-age" not in session_cookie and "expires" not in session_cookie

    csrf_cookie = cookies["__Host-cheena_csrf"]
    assert "httponly" not in csrf_cookie  # the frontend must read it
    assert "secure" in csrf_cookie
    assert "samesite=strict" in csrf_cookie


def test_development_cookie_mode_drops_secure_prefix(client, make_user, monkeypatch):
    monkeypatch.setattr(get_settings(), "cookie_secure", False)
    email, password = make_user(AccessCategory.COMPANY_USER)
    response = login(client, email, password)
    names = [c.split("=", 1)[0] for c in _set_cookie_headers(response)]
    assert "cheena_session" in names
    issued = [c for c in _set_cookie_headers(response) if "max-age=0" not in c.lower()]
    assert {c.split("=", 1)[0] for c in issued} == {"cheena_session", "cheena_csrf"}
    assert all("secure" not in c.lower() for c in issued)
    # Leftover "__Host-" cookies from secure mode are expired (Secure is required for that).
    expired = [c for c in _set_cookie_headers(response) if "max-age=0" in c.lower()]
    assert {c.split("=", 1)[0] for c in expired} == {"__Host-cheena_session", "__Host-cheena_csrf"}


def test_insecure_cookies_are_rejected_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production", cookie_secure=False, database_url="postgresql://x/y")


def test_credentials_are_never_logged(client, make_user, caplog):
    email, password = make_user(AccessCategory.COMPANY_ADMIN)
    with caplog.at_level(logging.DEBUG):
        login(client, email, password + "wrong")
        login(client, email, password)
    # Guard against a vacuous pass: the auth logger must actually have emitted records.
    assert "login failed: wrong password" in caplog.text
    assert "login succeeded" in caplog.text
    assert password not in caplog.text
    assert all(password not in str(record.args) for record in caplog.records)


def test_login_from_foreign_origin_is_rejected(client, make_user):
    email, password = make_user(AccessCategory.COMPANY_ADMIN)
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


def test_new_login_revokes_previous_session_in_same_browser(client, make_user, db: Session):
    email, password = make_user(AccessCategory.COMPANY_ADMIN)
    login(client, email, password)
    login(client, email, password)
    sessions = db.scalars(select(AuthenticationSession)).all()
    assert len(sessions) == 2
    assert sum(s.revoked_at is None for s in sessions) == 1
