"""Subscription expiry enforcement for the Company Workspace.

Time is controlled by patching the authoritative clock (``app.core.clock.utcnow``);
the system clock and the real development database are never touched.
Pakistan time is UTC+5, so 00:00 PKT on 06 Nov 2027 is 2027-11-05T19:00:00Z.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_valid_company_subscription
from app.core import clock
from app.main import app
from app.models import AccessCategory, AppSubscription, AuthenticationSession, User
from app.services.subscription import SubscriptionStatus
from app.services.subscription_access import company_access
from app.tasks.subscription_guard import (
    CompanySubscriptionInactive,
    ensure_company_subscription,
    requires_company_subscription,
)
from tests.conftest import csrf_header, login

START, EXPIRY = date(2026, 11, 5), date(2027, 11, 5)
COMPANY = "/api/v1/company/workspace"
COMPANY_ADMIN = "/api/v1/company/admin/workspace"
EXPIRED_MESSAGE = (
    "Your software subscription has expired. Please contact your administrator for renewal."
)

ACTIVE_UTC = datetime(2027, 6, 1, 6, 0, tzinfo=UTC)
LAST_SECOND_UTC = datetime(2027, 11, 5, 18, 59, 59, tzinfo=UTC)  # 23:59:59 PKT 05 Nov
BOUNDARY_UTC = datetime(2027, 11, 5, 19, 0, 0, tzinfo=UTC)  # 00:00:00 PKT 06 Nov
AFTER_UTC = datetime(2027, 11, 5, 19, 0, 1, tzinfo=UTC)
EXPIRED_UTC = datetime(2027, 12, 1, 6, 0, tzinfo=UTC)


@pytest.fixture
def set_clock(monkeypatch) -> Callable[[datetime], None]:
    def _set(at: datetime) -> None:
        monkeypatch.setattr(clock, "utcnow", lambda: at)

    return _set


@pytest.fixture
def subscription(db: Session) -> None:
    db.add(AppSubscription(company_name="Enforcement Co", start_date=START, expiry_date=EXPIRY))
    db.commit()


def _client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


def _code(response) -> str:
    return response.json()["error"]["code"]


# --- Policy and calendar boundaries ---------------------------------------------------


@pytest.mark.parametrize(
    ("at", "allowed", "status"),
    [
        (ACTIVE_UTC, True, SubscriptionStatus.ACTIVE),
        (datetime(2027, 10, 25, 6, 0, tzinfo=UTC), True, SubscriptionStatus.EXPIRING_SOON),
        (
            datetime(2027, 11, 4, 19, 0, tzinfo=UTC),
            True,
            SubscriptionStatus.EXPIRING_SOON,
        ),  # 00:00 PKT expiry day
        (LAST_SECOND_UTC, True, SubscriptionStatus.EXPIRING_SOON),
        (BOUNDARY_UTC, False, SubscriptionStatus.EXPIRED),
        (AFTER_UTC, False, SubscriptionStatus.EXPIRED),
        # Still 05 Nov in UTC but already 06 Nov in Pakistan: Pakistan time decides.
        (datetime(2027, 11, 5, 20, 0, tzinfo=UTC), False, SubscriptionStatus.EXPIRED),
        (datetime(2026, 11, 4, 18, 59, 59, tzinfo=UTC), False, SubscriptionStatus.SCHEDULED),
        (
            datetime(2026, 11, 4, 19, 0, 0, tzinfo=UTC),
            True,
            SubscriptionStatus.ACTIVE,
        ),  # start day 00:00 PKT
    ],
)
def test_company_access_boundaries(db, subscription, set_clock, at, allowed, status):
    set_clock(at)
    access = company_access(db)
    assert access.allowed is allowed
    assert access.status is status


def test_not_configured_fails_closed(db, set_clock):
    set_clock(ACTIVE_UTC)
    access = company_access(db)
    assert not access.allowed and access.code == "subscription_not_configured"
    assert db.get(AppSubscription, 1) is None  # nothing is created automatically


# --- Company login ------------------------------------------------------------------------


@pytest.mark.parametrize("category", [AccessCategory.COMPANY_ADMIN, AccessCategory.COMPANY_USER])
def test_company_login_blocked_after_expiry_without_session(
    client, make_user, subscription, set_clock, db, category
):
    email, password = make_user(category)
    set_clock(AFTER_UTC)

    r = login(client, email, password)

    assert r.status_code == 403
    assert r.json() == {"error": {"code": "subscription_expired", "message": EXPIRED_MESSAGE}}
    assert not r.headers.get_list("set-cookie")  # no usable session is issued
    user_id = db.scalar(select(User.id).where(User.email == email))
    assert (
        db.scalars(
            select(AuthenticationSession).where(AuthenticationSession.user_id == user_id)
        ).all()
        == []
    )


def test_company_login_allowed_on_final_second(client, make_user, subscription, set_clock):
    email, password = make_user(AccessCategory.COMPANY_ADMIN)
    set_clock(LAST_SECOND_UTC)
    assert login(client, email, password).status_code == 200
    assert client.get(COMPANY).status_code == 200


@pytest.mark.parametrize(
    ("at", "code"),
    [
        (datetime(2026, 10, 1, 6, 0, tzinfo=UTC), "subscription_not_started"),
    ],
)
def test_company_login_blocked_before_start(client, make_user, subscription, set_clock, at, code):
    email, password = make_user(AccessCategory.COMPANY_USER)
    set_clock(at)
    r = login(client, email, password)
    assert r.status_code == 403 and _code(r) == code


def test_company_login_blocked_when_not_configured(client, make_user, set_clock):
    email, password = make_user(AccessCategory.COMPANY_ADMIN)
    set_clock(ACTIVE_UTC)
    r = login(client, email, password)
    assert r.status_code == 403 and _code(r) == "subscription_not_configured"


def test_wrong_password_and_unknown_account_reveal_nothing_after_expiry(
    client, make_user, subscription, set_clock
):
    email, password = make_user(AccessCategory.COMPANY_ADMIN)
    set_clock(AFTER_UTC)
    wrong = login(client, email, password + "x")
    unknown = login(client, "nobody@example.test", password)
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert _code(wrong) == "invalid_credentials"


def test_inactive_company_account_still_reports_inactive(
    client, make_user, subscription, set_clock
):
    email, password = make_user(AccessCategory.COMPANY_USER, active=False)
    set_clock(AFTER_UTC)
    r = login(client, email, password)
    assert r.status_code == 403 and _code(r) == "account_inactive"


def test_repeated_expired_logins_do_not_trigger_lockout(client, make_user, subscription, set_clock):
    email, password = make_user(AccessCategory.COMPANY_ADMIN)
    set_clock(AFTER_UTC)
    for _ in range(8):
        assert _code(login(client, email, password)) == "subscription_expired"


# --- Existing sessions -------------------------------------------------------------------


def test_existing_company_session_is_blocked_immediately_at_the_boundary(
    client, make_user, subscription, set_clock
):
    email, password = make_user(AccessCategory.COMPANY_ADMIN)
    set_clock(LAST_SECOND_UTC)
    assert login(client, email, password).status_code == 200
    assert client.get(COMPANY).status_code == 200

    set_clock(BOUNDARY_UTC)  # no scheduler, no logout needed

    for path in (COMPANY, COMPANY_ADMIN):
        r = client.get(path)
        assert r.status_code == 403
        assert r.json() == {"error": {"code": "subscription_expired", "message": EXPIRED_MESSAGE}}

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["company_access"] == {"allowed": False, "code": "subscription_expired"}
    assert email not in r.text  # blocked responses carry no user or business data

    # Signing out still works (CSRF still required).
    assert client.post("/api/v1/auth/logout").status_code == 403
    assert client.post("/api/v1/auth/logout", headers=csrf_header(client)).status_code == 204


def test_me_reports_allowed_access_while_valid(client, make_user, subscription, set_clock):
    email, password = make_user(AccessCategory.COMPANY_USER)
    set_clock(ACTIVE_UTC)
    login(client, email, password)
    assert client.get("/api/v1/auth/me").json()["company_access"] == {"allowed": True, "code": None}


# --- Super Admin stays available ---------------------------------------------------------


def test_super_admin_login_dashboard_and_management_work_after_expiry(
    client, make_user, subscription, set_clock
):
    email, password = make_user(AccessCategory.SUPER_ADMIN)
    set_clock(EXPIRED_UTC)
    assert login(client, email, password).status_code == 200
    assert client.get("/api/v1/super-admin/dashboard").json()["subscription"]["status"] == "expired"
    assert client.get("/api/v1/super-admin/subscription").status_code == 200
    assert client.get("/api/v1/super-admin/subscription/renewals").status_code == 200
    assert client.get("/api/v1/auth/me").json()["company_access"] is None


def test_super_admin_never_reaches_company_apis_and_errors_stay_role_based(
    client, make_user, subscription, set_clock
):
    email, password = make_user(AccessCategory.SUPER_ADMIN)
    set_clock(EXPIRED_UTC)
    login(client, email, password)
    r = client.get(COMPANY)
    assert r.status_code == 403 and _code(r) == "permission_denied"


def test_company_accounts_still_cannot_reach_super_admin_apis(
    client, make_user, subscription, set_clock
):
    email, password = make_user(AccessCategory.COMPANY_ADMIN)
    set_clock(ACTIVE_UTC)
    login(client, email, password)
    for path in ("/api/v1/super-admin/dashboard", "/api/v1/super-admin/subscription"):
        r = client.get(path)
        assert r.status_code == 403 and _code(r) == "permission_denied"


def test_company_user_still_blocked_from_admin_routes_when_valid(
    client, make_user, subscription, set_clock
):
    email, password = make_user(AccessCategory.COMPANY_USER)
    set_clock(ACTIVE_UTC)
    login(client, email, password)
    assert client.get(COMPANY).status_code == 200
    r = client.get(COMPANY_ADMIN)
    assert r.status_code == 403 and _code(r) == "permission_denied"


def test_renewal_after_expiry_still_requires_csrf(client, make_user, subscription, set_clock):
    email, password = make_user(AccessCategory.SUPER_ADMIN)
    set_clock(EXPIRED_UTC)
    login(client, email, password)
    body = {
        "new_expiry_date": "2028-12-31",
        "expected_expiry_date": EXPIRY.isoformat(),
        "idempotency_key": "22222222-2222-4222-8222-222222222222",
    }
    r = client.post("/api/v1/super-admin/subscription/renew", json=body)
    assert r.status_code == 403 and _code(r) == "csrf_failed"


# --- Renewal restores access ----------------------------------------------------------------


def test_renewal_restores_retained_sessions_and_logins_but_not_revoked_sessions(
    make_user, subscription, set_clock, db
):
    admin_email, admin_pw = make_user(AccessCategory.COMPANY_ADMIN)
    user_email, user_pw = make_user(AccessCategory.COMPANY_USER)
    super_email, super_pw = make_user(AccessCategory.SUPER_ADMIN)

    set_clock(LAST_SECOND_UTC)
    with _client() as kept, _client() as signed_out, _client() as sa:
        login(kept, admin_email, admin_pw)
        login(signed_out, user_email, user_pw)
        revoked_token = signed_out.cookies.get("__Host-cheena_session")
        signed_out.post("/api/v1/auth/logout", headers=csrf_header(signed_out))

        set_clock(EXPIRED_UTC)
        assert _code(kept.get(COMPANY)) == "subscription_expired"
        assert _code(login(signed_out, user_email, user_pw)) == "subscription_expired"

        # Super Admin renews while expired (renewal must reach beyond Pakistan "today").
        login(sa, super_email, super_pw)
        r = sa.post(
            "/api/v1/super-admin/subscription/renew",
            json={
                "new_expiry_date": "2028-11-05",
                "expected_expiry_date": EXPIRY.isoformat(),
                "idempotency_key": "33333333-3333-4333-8333-333333333333",
            },
            headers=csrf_header(sa),
        )
        assert r.status_code == 201
        assert r.json()["subscription"]["status"] == "active"

        # Immediately effective: no restart, no re-login for the retained session.
        assert kept.get(COMPANY).status_code == 200
        # Existing credentials work again.
        assert login(signed_out, user_email, user_pw).status_code == 200
        # A session revoked earlier (sign-out) is never resurrected.
        signed_out.cookies.clear()
        signed_out.cookies.set("__Host-cheena_session", revoked_token)
        assert signed_out.get("/api/v1/auth/me").status_code == 401

    db.expire_all()
    record = db.get(AppSubscription, 1)
    assert record.start_date == START and record.expiry_date == date(2028, 11, 5)


# --- Coverage of the enforcement point --------------------------------------------------------


def _uses_subscription_guard(route: APIRoute) -> bool:
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        if dep.call is require_valid_company_subscription:
            return True
        stack.extend(dep.dependencies)
    return False


def test_every_company_route_is_guarded_and_no_other_route_is():
    routes = [r for r in app.routes if isinstance(r, APIRoute)]
    company = [r for r in routes if r.path.startswith("/api/v1/company")]
    others = [r for r in routes if not r.path.startswith("/api/v1/company")]
    assert company, "expected Company routes"
    assert all(_uses_subscription_guard(r) for r in company)
    assert not any(_uses_subscription_guard(r) for r in others)  # health, auth, super admin


def test_health_checks_are_never_blocked(client, subscription, set_clock):
    set_clock(EXPIRED_UTC)
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200


# --- Background tasks ---------------------------------------------------------------------


def test_company_task_guard_skips_when_expired_and_runs_when_valid(db, subscription, set_clock):
    calls: list[str] = []

    @requires_company_subscription
    def process_batch(name: str) -> str:
        calls.append(name)
        return "done"

    set_clock(AFTER_UTC)
    assert process_batch("queued-before-expiry") == {
        "status": "skipped",
        "reason": "subscription_expired",
    }
    assert calls == []

    set_clock(ACTIVE_UTC)
    assert process_batch("valid") == "done"
    assert calls == ["valid"]


def test_long_running_task_stops_at_the_next_checkpoint(db, subscription, set_clock):
    sent: list[int] = []

    @requires_company_subscription
    def sync_invoices(invoice_ids: list[int]) -> str:
        for i, invoice_id in enumerate(invoice_ids):
            if i == 2:
                set_clock(BOUNDARY_UTC)  # subscription expires mid-job
            ensure_company_subscription(db)  # checkpoint before each side effect
            sent.append(invoice_id)
        return "complete"

    set_clock(LAST_SECOND_UTC)
    assert sync_invoices([1, 2, 3, 4]) == {"status": "skipped", "reason": "subscription_expired"}
    assert sent == [1, 2]  # nothing sent after the boundary


def test_checkpoint_raises_typed_error(db, set_clock):
    set_clock(ACTIVE_UTC)
    with pytest.raises(CompanySubscriptionInactive) as exc:
        ensure_company_subscription(db)  # no subscription configured
    assert exc.value.code == "subscription_not_configured"


def test_system_tasks_are_not_subscription_guarded(db, set_clock):
    from app.tasks.system import ping

    set_clock(EXPIRED_UTC)
    assert ping() == "pong"


def test_expiring_soon_keeps_company_access(client, make_user, subscription, set_clock):
    email, password = make_user(AccessCategory.COMPANY_ADMIN)
    set_clock(datetime(2027, 10, 25, 6, 0, tzinfo=UTC) + timedelta(days=5))
    assert login(client, email, password).status_code == 200
    assert client.get(COMPANY).status_code == 200
