"""Super Admin dashboard: subscription rules, access control and data exposure."""

import io
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.cli import main
from app.models import AccessCategory, AppSubscription, AuditEvent
from app.services.subscription import (
    EXPIRING_SOON_DAYS,
    SubscriptionStatus,
    business_today,
    summarize,
)
from app.services.subscription_setup import (
    SubscriptionSetupError,
    configure_initial_subscription,
)
from tests.conftest import login

DASHBOARD = "/api/v1/super-admin/dashboard"
START, EXPIRY = date(2026, 1, 1), date(2026, 12, 31)  # 365 days


def sub(start: date = START, expiry: date = EXPIRY) -> AppSubscription:
    return AppSubscription(company_name="Test Co", start_date=start, expiry_date=expiry)


# --- Pure calculation rules ---------------------------------------------------


def test_not_configured():
    s = summarize(None, date(2026, 6, 1))
    assert s.status is SubscriptionStatus.NOT_CONFIGURED
    assert s.days_remaining is None and s.total_days is None


def test_active_mid_period_invariants():
    s = summarize(sub(), date(2026, 6, 1))
    assert s.status is SubscriptionStatus.ACTIVE
    assert s.total_days == 365
    assert s.days_used == 152  # Jan 1 .. Jun 1 inclusive
    assert s.days_remaining == 213
    assert s.days_used + s.days_remaining == s.total_days


def test_first_day():
    s = summarize(sub(), START)
    assert s.status is SubscriptionStatus.ACTIVE
    assert (s.days_used, s.days_remaining) == (1, 364)


@pytest.mark.parametrize(
    ("days_before_expiry", "expected"),
    [
        (EXPIRING_SOON_DAYS + 1, SubscriptionStatus.ACTIVE),
        (EXPIRING_SOON_DAYS, SubscriptionStatus.EXPIRING_SOON),
        (1, SubscriptionStatus.EXPIRING_SOON),
    ],
)
def test_expiring_soon_threshold(days_before_expiry, expected):
    s = summarize(sub(), EXPIRY - timedelta(days=days_before_expiry))
    assert s.status is expected
    assert s.days_remaining == days_before_expiry


def test_expiry_day_is_still_valid_with_zero_remaining():
    s = summarize(sub(), EXPIRY)
    assert s.status is SubscriptionStatus.EXPIRING_SOON  # valid, not expired
    assert s.days_remaining == 0
    assert s.days_used == s.total_days
    assert s.progress_percent == 100.0


def test_day_after_expiry_is_expired():
    s = summarize(sub(), EXPIRY + timedelta(days=1))
    assert s.status is SubscriptionStatus.EXPIRED
    assert s.days_remaining == 0
    assert s.days_used == s.total_days


def test_long_expired_never_negative():
    s = summarize(sub(), EXPIRY + timedelta(days=400))
    assert s.status is SubscriptionStatus.EXPIRED
    assert s.days_remaining == 0


def test_future_start_is_scheduled():
    s = summarize(sub(), START - timedelta(days=10))
    assert s.status is SubscriptionStatus.SCHEDULED
    assert s.days_used == 0
    assert s.days_remaining == s.total_days  # clamped, not 375
    assert s.days_until_start == 10
    assert s.progress_percent == 0.0


def test_single_day_subscription():
    s = summarize(sub(START, START), START)
    assert s.total_days == 1
    assert (s.days_used, s.days_remaining) == (1, 0)
    assert s.status is SubscriptionStatus.EXPIRING_SOON


def test_invalid_range_is_reported_not_computed():
    s = summarize(sub(EXPIRY, START), date(2026, 6, 1))
    assert s.status is SubscriptionStatus.INVALID
    assert s.days_remaining is None


def test_business_today_uses_pakistan_time():
    # 20:00 UTC on Dec 31 is already Jan 1 in Asia/Karachi (UTC+5).
    assert business_today(datetime(2026, 12, 31, 20, 0, tzinfo=UTC)) == date(2027, 1, 1)
    assert business_today(datetime(2026, 12, 31, 18, 59, tzinfo=UTC)) == date(2026, 12, 31)


# --- Database constraints -------------------------------------------------------


def test_only_one_subscription_row_can_exist(db: Session):
    db.add(sub())
    db.commit()
    with pytest.raises(IntegrityError):
        db.execute(text(
            "INSERT INTO app_subscription (id, company_name, start_date, expiry_date) "
            "VALUES (2, 'Other', '2026-01-01', '2026-02-01')"
        ))
    db.rollback()


def test_database_rejects_expiry_before_start(db: Session):
    db.add(sub(EXPIRY, START))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# --- API access ---------------------------------------------------------------


def _signed_in(client, make_user, category):
    email, password = make_user(category)
    assert login(client, email, password).status_code == 200
    return email


def test_unauthenticated_gets_401(client):
    r = client.get(DASHBOARD)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "not_authenticated"


@pytest.mark.parametrize("category", [AccessCategory.COMPANY_ADMIN, AccessCategory.COMPANY_USER])
def test_company_accounts_get_403(client, make_user, valid_subscription, category):
    _signed_in(client, make_user, category)
    r = client.get(DASHBOARD)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "permission_denied"


def test_super_admin_still_cannot_reach_company_apis(client, make_user):
    _signed_in(client, make_user, AccessCategory.SUPER_ADMIN)
    assert client.get("/api/v1/company/workspace").status_code == 403
    assert client.get("/api/v1/company/admin/workspace").status_code == 403


def test_not_configured_dashboard(client, make_user):
    _signed_in(client, make_user, AccessCategory.SUPER_ADMIN)
    body = client.get(DASHBOARD).json()
    assert body["subscription"]["status"] == "not_configured"
    assert body["subscription"]["days_remaining"] is None
    assert body["company"] == {"name": None, "account_type": "single_company"}
    assert body["timezone"] == "Asia/Karachi"
    assert body["today"] == business_today().isoformat()


def test_configured_dashboard_uses_backend_dates(client, make_user, db: Session):
    today = business_today()
    db.add(AppSubscription(company_name="Cheena Test", start_date=today - timedelta(days=9),
                           expiry_date=today + timedelta(days=20)))
    db.commit()
    _signed_in(client, make_user, AccessCategory.SUPER_ADMIN)

    s = client.get(DASHBOARD).json()["subscription"]

    assert s["status"] == "active"
    assert (s["total_days"], s["days_used"], s["days_remaining"]) == (30, 10, 20)
    assert s["expiring_soon_threshold_days"] == EXPIRING_SOON_DAYS


def test_super_admin_still_works_after_subscription_expired(client, make_user, db: Session):
    today = business_today()
    db.add(AppSubscription(company_name="Cheena Test", start_date=today - timedelta(days=60),
                           expiry_date=today - timedelta(days=1)))
    db.commit()
    _signed_in(client, make_user, AccessCategory.SUPER_ADMIN)
    r = client.get(DASHBOARD)
    assert r.status_code == 200
    assert r.json()["subscription"]["status"] == "expired"
    assert r.json()["subscription"]["days_remaining"] == 0


# --- Company Admin contact ----------------------------------------------------------


def test_contact_not_found(client, make_user):
    _signed_in(client, make_user, AccessCategory.SUPER_ADMIN)
    contact = client.get(DASHBOARD).json()["company_admin"]
    assert contact["status"] == "not_found"
    assert contact["email"] is None


def test_contact_single_company_admin(client, make_user):
    admin_email, _ = make_user(AccessCategory.COMPANY_ADMIN)
    make_user(AccessCategory.COMPANY_USER)  # must never appear
    _signed_in(client, make_user, AccessCategory.SUPER_ADMIN)
    contact = client.get(DASHBOARD).json()["company_admin"]
    assert contact == {
        "status": "available",
        "count": 1,
        "full_name": "Test company_admin",
        "email": admin_email,
        "is_active": True,
    }


def test_contact_inactive_admin_is_flagged(client, make_user):
    make_user(AccessCategory.COMPANY_ADMIN, active=False)
    _signed_in(client, make_user, AccessCategory.SUPER_ADMIN)
    assert client.get(DASHBOARD).json()["company_admin"]["is_active"] is False


def test_multiple_admins_are_not_picked_arbitrarily(client, make_user):
    make_user(AccessCategory.COMPANY_ADMIN)
    make_user(AccessCategory.COMPANY_ADMIN)
    _signed_in(client, make_user, AccessCategory.SUPER_ADMIN)
    contact = client.get(DASHBOARD).json()["company_admin"]
    assert contact["status"] == "multiple"
    assert contact["count"] == 2
    assert contact["email"] is None and contact["full_name"] is None


def test_response_exposes_no_sensitive_or_business_data(client, make_user):
    make_user(AccessCategory.COMPANY_ADMIN)
    user_email, _ = make_user(AccessCategory.COMPANY_USER)
    super_email = _signed_in(client, make_user, AccessCategory.SUPER_ADMIN)
    r = client.get(DASHBOARD)
    body, raw = r.json(), r.text

    assert set(body) == {"today", "timezone", "company", "company_admin", "subscription"}
    assert set(body["company_admin"]) == {"status", "count", "full_name", "email", "is_active"}
    for forbidden in ("password", "hash", "argon2", "token", "session", "csrf", "shop",
                      "invoice", "fbr", "sales", user_email, super_email):
        assert forbidden not in raw.lower(), forbidden
    assert r.headers["cache-control"] == "no-store"


# --- Initial subscription setup (CLI) ------------------------------------------------


def test_cli_configures_initial_subscription_once(db: Session):
    args = ["configure-subscription", "--company-name", "Cheena Test",
            "--start-date", "2026-01-01", "--expiry-date", "2026-12-31", "--yes"]
    out = io.StringIO()
    assert main(args, out=out) == 0
    record = db.get(AppSubscription, 1)
    assert (record.start_date, record.expiry_date) == (START, EXPIRY)
    assert db.scalar(select(AuditEvent.action)) == "subscription.configured"

    again = io.StringIO()
    assert main(args[:-3] + ["--expiry-date", "2027-12-31", "--yes"], out=again) == 1
    assert "renewal" in again.getvalue()
    db.expire_all()
    assert db.get(AppSubscription, 1).expiry_date == EXPIRY  # unchanged


def test_cli_rejects_bad_input_and_cancel(db: Session):
    bad = ["configure-subscription", "--company-name", "X",
           "--start-date", "2026-13-01", "--expiry-date", "2026-12-31", "--yes"]
    assert main(bad, out=io.StringIO()) == 2
    cancel = ["configure-subscription", "--company-name", "X",
              "--start-date", "2026-01-01", "--expiry-date", "2026-12-31"]
    assert main(cancel, out=io.StringIO(), prompt=lambda _: "n") == 1
    assert db.get(AppSubscription, 1) is None


def test_setup_rejects_reversed_dates(db: Session):
    with pytest.raises(SubscriptionSetupError):
        configure_initial_subscription(db, "X", EXPIRY, START, "cli:test")
