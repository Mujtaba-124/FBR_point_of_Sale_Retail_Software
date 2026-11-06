"""Company Admin dashboard summary: access control, subscription guard, honest metrics."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import AccessCategory, AppSubscription, User
from app.services.subscription import business_today
from tests.conftest import login

URL = "/api/v1/company/dashboard/summary"


def signed_in(client: TestClient, make_user, category: AccessCategory) -> TestClient:
    email, password = make_user(category)
    assert login(client, email, password).status_code == 200
    return client


def test_unauthenticated_is_401(client: TestClient) -> None:
    assert client.get(URL).status_code == 401


@pytest.mark.usefixtures("valid_subscription")
def test_super_admin_is_denied(client: TestClient, make_user) -> None:
    res = signed_in(client, make_user, AccessCategory.SUPER_ADMIN).get(URL)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "permission_denied"


@pytest.mark.usefixtures("valid_subscription")
def test_company_user_is_denied(client: TestClient, make_user) -> None:
    res = signed_in(client, make_user, AccessCategory.COMPANY_USER).get(URL)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "permission_denied"


@pytest.mark.usefixtures("valid_subscription")
def test_company_admin_gets_real_and_unavailable_metrics(
    client: TestClient, make_user, db: Session
) -> None:
    make_user(AccessCategory.SUPER_ADMIN)  # never counted
    make_user(AccessCategory.COMPANY_USER)
    make_user(AccessCategory.COMPANY_USER, active=False)  # inactive: not counted
    make_user(AccessCategory.COMPANY_ADMIN, active=False)
    res = signed_in(client, make_user, AccessCategory.COMPANY_ADMIN).get(URL)
    assert res.status_code == 200
    data = res.json()
    assert data["company"] == {"name": "Test Company"}
    metrics = data["metrics"]
    # The signed-in Company Admin + one active Company User.
    assert metrics["active_users"] == {"available": True, "value": 2, "unavailable_reason": None}
    # Shop Management exists now: a real (here empty) count, not "unavailable".
    assert metrics["total_shops"] == {"available": True, "value": 0, "unavailable_reason": None}
    assert metrics["active_shops"] == {"available": True, "value": 0, "unavailable_reason": None}
    for key, reason in (
        ("pending_approvals", "approval_workflow_not_available"),
        ("pending_fbr_sync", "fbr_sync_not_available"),
    ):
        # Not built yet: no value at all, never a fabricated zero.
        assert metrics[key] == {"available": False, "value": None, "unavailable_reason": reason}
    assert data["sales_overview"] == {
        "available": False,
        "unavailable_reason": "excel_upload_not_available",
    }
    assert data["recent_uploads"]["available"] is False


@pytest.mark.usefixtures("valid_subscription")
def test_deactivated_admin_loses_dashboard_access(
    client: TestClient, make_user, db: Session
) -> None:
    signed_in(client, make_user, AccessCategory.COMPANY_ADMIN)
    # The viewer is always an active Company Admin, so the count is never a fake 0;
    db.execute(
        update(User)
        .where(User.access_category != AccessCategory.SUPER_ADMIN)
        .values(is_active=False)
    )
    db.commit()
    res = client.get(URL)
    # deactivating the account ends its session instead (401).
    assert res.status_code == 401


@pytest.mark.usefixtures("valid_subscription")
def test_response_contains_no_account_details_or_secrets(client: TestClient, make_user) -> None:
    super_email, _ = make_user(AccessCategory.SUPER_ADMIN)
    staff_email, _ = make_user(AccessCategory.COMPANY_USER)
    res = signed_in(client, make_user, AccessCategory.COMPANY_ADMIN).get(URL)
    body = res.text
    for needle in (super_email, staff_email, "password", "hash", "token", "smtp", "expiry"):
        assert needle not in body.lower()
    assert set(res.json()) == {
        "company",
        "metrics",
        "sales_overview",
        "recent_uploads",
        "shop_allowance",  # aggregate only (Phase 3.1)
        "context",  # shop context (Phase 3.2)
        "metric_scopes",
    }
    assert set(res.json()["shop_allowance"]) == {
        "mode",
        "max_shops",
        "registered_shops",
        "available_slots",
        "at_capacity",
        "over_limit",
    }


@pytest.mark.parametrize(
    ("start_offset", "expiry_offset", "code"),
    [
        (-30, -1, "subscription_expired"),
        (5, 300, "subscription_not_started"),
    ],
)
def test_subscription_guard_blocks_the_dashboard(
    client: TestClient, make_user, db: Session, start_offset: int, expiry_offset: int, code: str
) -> None:
    today = business_today()
    db.add(
        AppSubscription(
            company_name="Test Company",
            start_date=today - timedelta(days=30),
            expiry_date=today + timedelta(days=300),
        )
    )
    db.commit()
    signed_in(client, make_user, AccessCategory.COMPANY_ADMIN)
    db.execute(
        update(AppSubscription).values(
            start_date=today + timedelta(days=start_offset),
            expiry_date=today + timedelta(days=expiry_offset),
        )
    )
    db.commit()
    res = client.get(URL)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == code
    # The Super Admin workspace keeps working while the company is restricted.
    other = TestClient(client.app, base_url="https://testserver")
    email, password = make_user(AccessCategory.SUPER_ADMIN)
    assert login(other, email, password).status_code == 200
    assert other.get("/api/v1/super-admin/dashboard").status_code == 200


def test_missing_subscription_blocks_the_dashboard(client: TestClient, make_user) -> None:
    # Company sign-in itself is refused without a subscription (fail closed).
    email, password = make_user(AccessCategory.COMPANY_ADMIN)
    assert login(client, email, password).status_code == 403
    assert client.get(URL).status_code == 401
