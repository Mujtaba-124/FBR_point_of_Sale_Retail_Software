"""Changing an account's email via the operator CLI/service."""

import io
import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cli import main
from app.models import AccessCategory, AuditEvent, AuthenticationSession, User
from app.services.account_admin import (
    EMAIL_CHANGE_REFUSED,
    EMAIL_CHANGED,
    AccountChangeError,
    change_user_email,
)
from tests.conftest import login

# Company accounts sign in here, which requires a valid subscription.
pytestmark = pytest.mark.usefixtures("valid_subscription")

SUPER = "/api/v1/super-admin/workspace"
COMPANY = "/api/v1/company/workspace"


def _snapshot(db: Session, email: str) -> tuple:
    db.expire_all()
    u = db.scalar(select(User).where(User.email == email))
    return (u.id, u.password_hash, u.access_category, u.is_active, u.created_at, u.full_name)


def test_change_preserves_identity_password_role_and_status(db: Session, make_user):
    email, password = make_user(AccessCategory.SUPER_ADMIN)
    before = _snapshot(db, email)

    result = change_user_email(db, email, "New.Owner@Example.test", password, "cli:test")

    assert result.new_email == "new.owner@example.test"
    after = _snapshot(db, "new.owner@example.test")
    assert after == before
    assert db.scalar(select(User).where(User.email == email)) is None
    assert len(db.scalars(select(User)).all()) == 1  # no account created or deleted


def test_sessions_are_revoked_and_new_email_signs_in(client, db: Session, make_user):
    email, password = make_user(AccessCategory.COMPANY_ADMIN)
    assert login(client, email, password).status_code == 200
    assert client.get(COMPANY).status_code == 200

    result = change_user_email(db, email, "admin.new@example.test", password, "cli:test")

    assert result.sessions_revoked == 1
    assert client.get("/api/v1/auth/me").status_code == 401  # old session is dead
    db.expire_all()
    assert all(s.revoked_at is not None for s in db.scalars(select(AuthenticationSession)))

    assert login(client, email, password).status_code == 401  # old email no longer works
    assert login(client, "admin.new@example.test", password).status_code == 200
    me = client.get("/api/v1/auth/me").json()
    assert me["access_category"] == "company_admin"
    assert client.get(COMPANY).status_code == 200
    assert client.get(SUPER).status_code == 403  # separation unchanged


def test_super_admin_keeps_access_category_and_separation(client, db: Session, make_user):
    email, password = make_user(AccessCategory.SUPER_ADMIN)
    change_user_email(db, email, "owner.new@example.test", password, "cli:test")
    assert login(client, "owner.new@example.test", password).status_code == 200
    assert client.get(SUPER).status_code == 200
    assert client.get(COMPANY).status_code == 403


def test_wrong_account_password_is_refused_and_changes_nothing(db: Session, make_user):
    email, password = make_user(AccessCategory.SUPER_ADMIN)
    before = _snapshot(db, email)
    with pytest.raises(AccountChangeError, match="incorrect"):
        change_user_email(db, email, "x.new@example.test", password + "x", "cli:test")
    assert _snapshot(db, email) == before


def test_unknown_account_gets_the_same_message(db: Session):
    with pytest.raises(AccountChangeError, match="incorrect"):
        change_user_email(db, "ghost@example.test", "x@example.test", "whatever-pass", "cli:test")


def test_new_email_must_be_unique_case_insensitively(db: Session, make_user):
    email, password = make_user(AccessCategory.SUPER_ADMIN)
    other, _ = make_user(AccessCategory.COMPANY_ADMIN)
    before = _snapshot(db, email)
    with pytest.raises(AccountChangeError, match="already used"):
        change_user_email(db, email, other.upper(), password, "cli:test")
    assert _snapshot(db, email) == before


@pytest.mark.parametrize("bad", ["not-an-email", "a@b", "two@@example.test", "sp ace@example.test"])
def test_invalid_new_email_is_refused(db: Session, make_user, bad):
    email, password = make_user(AccessCategory.SUPER_ADMIN)
    with pytest.raises(AccountChangeError, match="not valid"):
        change_user_email(db, email, bad, password, "cli:test")


def test_same_email_is_refused(db: Session, make_user):
    email, password = make_user(AccessCategory.SUPER_ADMIN)
    with pytest.raises(AccountChangeError, match="same"):
        change_user_email(db, email, email.upper(), password, "cli:test")


def test_audit_events_record_change_without_secrets(db: Session, make_user):
    email, password = make_user(AccessCategory.COMPANY_ADMIN)
    with pytest.raises(AccountChangeError):
        change_user_email(db, email, "y.new@example.test", password + "x", "cli:test")
    change_user_email(db, email, "y.new@example.test", password, "cli:test")

    events = db.scalars(select(AuditEvent).order_by(AuditEvent.occurred_at)).all()
    assert [e.action for e in events] == [EMAIL_CHANGE_REFUSED, EMAIL_CHANGED]
    changed = events[1]
    user = db.scalar(select(User))
    assert changed.target_user_id == user.id
    assert changed.actor == "cli:test"
    assert changed.details["old_email"] == email
    assert changed.details["new_email"] == "y.new@example.test"
    assert changed.details["email_verified"] is False
    serialized = json.dumps([e.details for e in events])
    assert password not in serialized
    assert user.password_hash not in serialized
    assert "$argon2" not in serialized


def test_app_log_masks_emails_and_never_logs_password(db: Session, make_user, caplog):
    email, password = make_user(AccessCategory.COMPANY_ADMIN)
    with caplog.at_level("DEBUG"):
        change_user_email(db, email, "masked.new@example.test", password, "cli:test")
    assert password not in caplog.text
    assert "masked.new@example.test" not in caplog.text
    assert "ma***@example.test" in caplog.text


def test_cli_interactive_flow(db: Session, make_user):
    email, password = make_user(AccessCategory.SUPER_ADMIN)
    answers = iter(["owner.cli@example.test", "OWNER.CLI@example.test"])
    out = io.StringIO()

    code = main(
        ["change-email", "--current-email", email],
        out=out,
        prompt=lambda _: next(answers),
        secret=lambda _: password,
    )

    assert code == 0
    text = out.getvalue()
    assert "owner.cli@example.test" in text
    assert "NOT verified" in text
    assert password not in text
    assert db.scalar(select(User.email)) == "owner.cli@example.test"


def test_cli_refuses_mismatched_confirmation(db: Session, make_user):
    email, password = make_user(AccessCategory.SUPER_ADMIN)
    answers = iter(["one@example.test", "two@example.test"])
    out = io.StringIO()
    code = main(
        ["change-email", "--current-email", email],
        out=out,
        prompt=lambda _: next(answers),
        secret=lambda _: password,
    )
    assert code == 2
    assert db.scalar(select(User.email)) == email


def test_cli_wrong_password_exits_1(db: Session, make_user):
    email, password = make_user(AccessCategory.SUPER_ADMIN)
    out = io.StringIO()
    code = main(
        ["change-email", "--current-email", email, "--new-email", "z@example.test",
         "--password-stdin"],
        stdin=io.StringIO("wrong-password\n"),
        out=out,
    )
    assert code == 1
    assert "Refused" in out.getvalue()
    assert db.scalar(select(User.email)) == email
