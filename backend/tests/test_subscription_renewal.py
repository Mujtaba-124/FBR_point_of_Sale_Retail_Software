"""Subscription renewal: rules, authorization, concurrency, atomicity, history and audit.

Runs only against the disposable test database; the real subscription is never used.
"""

import threading
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.db.session import get_engine
from app.models import AccessCategory, AppSubscription, AuditEvent, SubscriptionRenewal, User
from app.services import subscription_renewal as svc
from app.services.subscription import SubscriptionStatus, business_today, summarize
from tests.conftest import csrf_header, login

RENEW = "/api/v1/super-admin/subscription/renew"
SUBSCRIPTION = "/api/v1/super-admin/subscription"
HISTORY = "/api/v1/super-admin/subscription/renewals"


def _today() -> date:
    return business_today()


@dataclass(frozen=True)
class Original:
    """The subscription's dates as created (not a live ORM object, so never refreshed)."""

    start_date: date
    expiry_date: date


@pytest.fixture
def subscription(db: Session) -> Original:
    today = _today()
    start, expiry = today - timedelta(days=100), today + timedelta(days=264)
    db.add(AppSubscription(company_name="Renewal Test Co", start_date=start, expiry_date=expiry))
    db.commit()
    return Original(start, expiry)


@pytest.fixture
def super_admin(db: Session, make_user) -> User:
    email, _ = make_user(AccessCategory.SUPER_ADMIN)
    return db.scalar(select(User).where(User.email == email))


def _payload(current_expiry: date, days: int = 365, **extra) -> dict:
    return {
        "new_expiry_date": (current_expiry + timedelta(days=days)).isoformat(),
        "expected_expiry_date": current_expiry.isoformat(),
        "idempotency_key": str(uuid.uuid4()),
        **extra,
    }


def _signed_in_super(client, make_user) -> None:
    email, password = make_user(AccessCategory.SUPER_ADMIN)
    assert login(client, email, password).status_code == 200


def _expiry(db: Session) -> date:
    db.expire_all()
    return db.get(AppSubscription, 1).expiry_date


# --- Authorization -------------------------------------------------------------------


@pytest.mark.parametrize("path", [SUBSCRIPTION, HISTORY])
def test_reads_require_authentication(client, path):
    assert client.get(path).status_code == 401


def test_renew_requires_authentication(client, subscription):
    r = client.post(RENEW, json=_payload(subscription.expiry_date))
    assert r.status_code == 401


@pytest.mark.parametrize("category", [AccessCategory.COMPANY_ADMIN, AccessCategory.COMPANY_USER])
def test_company_accounts_are_denied(client, make_user, subscription, db, category):
    email, password = make_user(category)
    login(client, email, password)
    for path in (SUBSCRIPTION, HISTORY):
        assert client.get(path).status_code == 403
    r = client.post(RENEW, json=_payload(subscription.expiry_date), headers=csrf_header(client))
    assert r.status_code == 403
    assert db.scalar(select(SubscriptionRenewal)) is None


def test_renew_requires_csrf_token(client, make_user, subscription, db):
    _signed_in_super(client, make_user)
    before = subscription.expiry_date
    no_token = client.post(RENEW, json=_payload(before))
    wrong = client.post(RENEW, json=_payload(before), headers={"X-CSRF-Token": "forged"})
    assert no_token.status_code == wrong.status_code == 403
    assert no_token.json()["error"]["code"] == "csrf_failed"
    assert _expiry(db) == before


# --- Successful renewal --------------------------------------------------------------


def test_super_admin_renewal_extends_expiry_and_records_history(
    client, make_user, subscription, db
):
    _signed_in_super(client, make_user)
    start, old_expiry = subscription.start_date, subscription.expiry_date
    payload = _payload(old_expiry, 365, renewal_note="  Annual renewal  ")

    r = client.post(RENEW, json=payload, headers=csrf_header(client))

    assert r.status_code == 201
    body = r.json()
    assert body["replayed"] is False
    assert body["renewal"]["previous_expiry_date"] == old_expiry.isoformat()
    assert body["renewal"]["new_expiry_date"] == payload["new_expiry_date"]
    assert body["renewal"]["renewal_note"] == "Annual renewal"
    assert body["subscription"]["expiry_date"] == payload["new_expiry_date"]
    assert body["subscription"]["start_date"] == start.isoformat()  # never changed

    db.expire_all()
    record = db.get(AppSubscription, 1)
    assert record.start_date == start
    assert record.expiry_date == old_expiry + timedelta(days=365)
    assert record.last_renewed_on == _today()
    assert len(db.scalars(select(SubscriptionRenewal)).all()) == 1


def test_dashboard_and_management_reflect_the_renewal(client, make_user, subscription):
    _signed_in_super(client, make_user)
    old = client.get("/api/v1/super-admin/dashboard").json()["subscription"]
    client.post(RENEW, json=_payload(subscription.expiry_date, 30), headers=csrf_header(client))

    dash = client.get("/api/v1/super-admin/dashboard").json()["subscription"]
    mgmt = client.get(SUBSCRIPTION).json()

    assert dash["days_remaining"] == old["days_remaining"] + 30
    assert dash["total_days"] == old["total_days"] + 30
    assert dash["days_used"] == old["days_used"]
    assert dash["last_renewed_on"] == _today().isoformat()
    assert mgmt["subscription"] == dash
    assert (
        mgmt["renewal"]["min_new_expiry_date"]
        == (date.fromisoformat(dash["expiry_date"]) + timedelta(days=1)).isoformat()
    )


def test_audit_event_is_written_without_secrets(client, make_user, subscription, db):
    _signed_in_super(client, make_user)
    r = client.post(RENEW, json=_payload(subscription.expiry_date), headers=csrf_header(client))
    renewal = r.json()["renewal"]

    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "subscription.renewed"))
    actor = db.scalar(select(User).where(User.access_category == AccessCategory.SUPER_ADMIN))
    assert event.actor == f"user:{actor.id}"
    assert event.details == {
        "subscription_id": 1,
        "renewal_id": renewal["id"],
        "previous_expiry_date": renewal["previous_expiry_date"],
        "new_expiry_date": renewal["new_expiry_date"],
        "renewed_by_user_id": str(actor.id),
    }
    assert event.occurred_at is not None
    assert "hash" not in str(event.details) and "token" not in str(event.details)


def test_history_is_newest_first_paginated_and_read_only(client, make_user, subscription):
    _signed_in_super(client, make_user)
    expiry = subscription.expiry_date
    for _ in range(3):
        r = client.post(RENEW, json=_payload(expiry, 10), headers=csrf_header(client))
        expiry = date.fromisoformat(r.json()["renewal"]["new_expiry_date"])

    page = client.get(HISTORY, params={"limit": 2}).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    first, second = page["items"]
    assert first["new_expiry_date"] == expiry.isoformat()
    assert first["previous_expiry_date"] == second["new_expiry_date"]
    assert set(first["renewed_by"]) == {"full_name", "email"}
    rest = client.get(HISTORY, params={"limit": 2, "offset": 2}).json()
    assert len(rest["items"]) == 1

    # No write/delete endpoints exist for history.
    item = f"{HISTORY}/{first['id']}"
    assert client.delete(item, headers=csrf_header(client)).status_code in (404, 405)
    assert client.put(HISTORY, json={}, headers=csrf_header(client)).status_code == 405


def test_history_empty_state(client, make_user, subscription):
    _signed_in_super(client, make_user)
    assert client.get(HISTORY).json() == {"items": [], "total": 0, "limit": 10, "offset": 0}


# --- Validation ------------------------------------------------------------------


@pytest.mark.parametrize("days", [0, -1, -30])
def test_unchanged_or_earlier_expiry_is_rejected(client, make_user, subscription, db, days):
    _signed_in_super(client, make_user)
    r = client.post(
        RENEW, json=_payload(subscription.expiry_date, days), headers=csrf_header(client)
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_renewal"
    assert _expiry(db) == subscription.expiry_date


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(new_expiry_date="2027-02-30"),
        lambda p: p.update(new_expiry_date="not-a-date"),
        lambda p: p.update(idempotency_key="not-a-uuid"),
        lambda p: p.pop("expected_expiry_date"),
        lambda p: p.update(start_date="2020-01-01"),  # unknown fields are rejected
        lambda p: p.update(renewal_note="x" * 501),
        lambda p: p.update(new_expiry_date="2099-12-31"),  # beyond the 10-year cap
    ],
)
def test_invalid_input_is_rejected(client, make_user, subscription, db, mutate):
    _signed_in_super(client, make_user)
    payload = _payload(subscription.expiry_date)
    mutate(payload)
    r = client.post(RENEW, json=payload, headers=csrf_header(client))
    assert r.status_code == 422
    assert _expiry(db) == subscription.expiry_date
    assert db.scalar(select(SubscriptionRenewal)) is None


def test_renewal_without_configured_subscription_is_refused(client, make_user, db):
    _signed_in_super(client, make_user)
    today = _today()
    r = client.post(RENEW, json=_payload(today), headers=csrf_header(client))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "subscription_not_configured"
    assert db.get(AppSubscription, 1) is None  # renewal never creates a subscription
    assert client.get(SUBSCRIPTION).json()["renewal"]["can_renew"] is False


def test_renewal_after_expiry_must_reach_beyond_today(db, super_admin):
    today = _today()
    db.add(
        AppSubscription(
            company_name="X",
            start_date=today - timedelta(days=400),
            expiry_date=today - timedelta(days=35),
        )
    )
    db.commit()
    expired = db.get(AppSubscription, 1).expiry_date

    with pytest.raises(AppError) as too_short:  # later than old expiry, but not past today
        svc.renew_subscription(
            db,
            actor=super_admin,
            new_expiry_date=today,
            expected_expiry_date=expired,
            idempotency_key=uuid.uuid4(),
        )
    assert too_short.value.status_code == 422

    outcome = svc.renew_subscription(
        db,
        actor=super_admin,
        new_expiry_date=today + timedelta(days=365),
        expected_expiry_date=expired,
        idempotency_key=uuid.uuid4(),
    )
    assert outcome.created
    record = db.get(AppSubscription, 1)
    summary = summarize(record, today)
    assert summary.status is SubscriptionStatus.ACTIVE
    assert summary.days_remaining == 365
    assert record.start_date == today - timedelta(days=400)  # start date untouched


# --- Concurrency, staleness, duplicates ---------------------------------------------------


def test_stale_form_is_rejected_with_409(client, make_user, subscription, db):
    _signed_in_super(client, make_user)
    stale = _payload(subscription.expiry_date - timedelta(days=1), 400)
    r = client.post(RENEW, json=stale, headers=csrf_header(client))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "stale_subscription"
    assert _expiry(db) == subscription.expiry_date


def test_second_form_based_on_old_expiry_is_stale_after_a_renewal(
    client, make_user, subscription, db
):
    _signed_in_super(client, make_user)
    first = _payload(subscription.expiry_date, 30)
    second = _payload(subscription.expiry_date, 60)  # opened before the first was saved
    assert client.post(RENEW, json=first, headers=csrf_header(client)).status_code == 201
    r = client.post(RENEW, json=second, headers=csrf_header(client))
    assert r.status_code == 409
    assert _expiry(db) == subscription.expiry_date + timedelta(days=30)


def test_duplicate_submission_is_idempotent(client, make_user, subscription, db):
    _signed_in_super(client, make_user)
    payload = _payload(subscription.expiry_date, 30)

    first = client.post(RENEW, json=payload, headers=csrf_header(client))
    again = client.post(RENEW, json=payload, headers=csrf_header(client))

    assert first.status_code == 201 and again.status_code == 200
    assert again.json()["replayed"] is True
    assert again.json()["renewal"]["id"] == first.json()["renewal"]["id"]
    assert len(db.scalars(select(SubscriptionRenewal)).all()) == 1
    assert (
        len(db.scalars(select(AuditEvent).where(AuditEvent.action == "subscription.renewed")).all())
        == 1
    )
    assert _expiry(db) == subscription.expiry_date + timedelta(days=30)


def test_reusing_a_key_with_different_details_conflicts(client, make_user, subscription):
    _signed_in_super(client, make_user)
    payload = _payload(subscription.expiry_date, 30)
    client.post(RENEW, json=payload, headers=csrf_header(client))
    tampered = {
        **payload,
        "new_expiry_date": (subscription.expiry_date + timedelta(days=90)).isoformat(),
    }
    r = client.post(RENEW, json=tampered, headers=csrf_header(client))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "idempotency_conflict"


def _race(super_admin_id, args_list):
    """Run renewals at the same moment in separate connections."""
    barrier = threading.Barrier(len(args_list))
    results: list = [None] * len(args_list)
    factory = sessionmaker(bind=get_engine(), autoflush=False)

    def worker(i, kwargs):
        session = factory()
        try:
            actor = session.get(User, super_admin_id)
            barrier.wait()
            results[i] = svc.renew_subscription(session, actor=actor, **kwargs)
        except AppError as exc:
            results[i] = exc
        finally:
            session.close()

    threads = [threading.Thread(target=worker, args=(i, a)) for i, a in enumerate(args_list)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


def test_concurrent_renewals_cannot_both_apply(db, subscription, super_admin):
    expiry = subscription.expiry_date
    results = _race(
        super_admin.id,
        [
            {
                "new_expiry_date": expiry + timedelta(days=30),
                "expected_expiry_date": expiry,
                "idempotency_key": uuid.uuid4(),
            },
            {
                "new_expiry_date": expiry + timedelta(days=60),
                "expected_expiry_date": expiry,
                "idempotency_key": uuid.uuid4(),
            },
        ],
    )
    winners = [r for r in results if isinstance(r, svc.RenewalOutcome)]
    losers = [r for r in results if isinstance(r, AppError)]
    assert len(winners) == 1 and len(losers) == 1
    assert losers[0].status_code == 409 and losers[0].code == "stale_subscription"
    assert _expiry(db) == winners[0].renewal.new_expiry_date
    assert len(db.scalars(select(SubscriptionRenewal)).all()) == 1


def test_concurrent_duplicate_requests_create_one_renewal(db, subscription, super_admin):
    expiry, key = subscription.expiry_date, uuid.uuid4()
    same = {
        "new_expiry_date": expiry + timedelta(days=30),
        "expected_expiry_date": expiry,
        "idempotency_key": key,
    }
    results = _race(super_admin.id, [dict(same), dict(same)])
    assert all(isinstance(r, svc.RenewalOutcome) for r in results)
    assert sorted(r.created for r in results) == [False, True]
    assert len(db.scalars(select(SubscriptionRenewal)).all()) == 1


def test_failure_mid_transaction_leaves_no_partial_data(db, subscription, super_admin, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("audit store unavailable")

    monkeypatch.setattr(svc, "_record_audit", boom)
    with pytest.raises(RuntimeError):
        svc.renew_subscription(
            db,
            actor=super_admin,
            new_expiry_date=subscription.expiry_date + timedelta(days=30),
            expected_expiry_date=subscription.expiry_date,
            idempotency_key=uuid.uuid4(),
        )
    assert _expiry(db) == subscription.expiry_date
    assert db.get(AppSubscription, 1).last_renewed_on is None
    assert db.scalar(select(SubscriptionRenewal)) is None
    assert db.scalar(select(AuditEvent)) is None


def test_history_rows_cannot_be_updated_or_deleted(db, subscription, super_admin):
    svc.renew_subscription(
        db,
        actor=super_admin,
        new_expiry_date=subscription.expiry_date + timedelta(days=30),
        expected_expiry_date=subscription.expiry_date,
        idempotency_key=uuid.uuid4(),
    )
    for statement in (
        "UPDATE subscription_renewals SET renewal_note = 'edited'",
        "DELETE FROM subscription_renewals",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            db.execute(text(statement))
        db.rollback()
    assert len(db.scalars(select(SubscriptionRenewal)).all()) == 1


def test_database_rejects_non_extending_history_rows(db, subscription, super_admin):
    with pytest.raises(DBAPIError):
        db.execute(
            text(
                "INSERT INTO subscription_renewals (subscription_id, previous_expiry_date, "
                "new_expiry_date, renewed_by_user_id, idempotency_key) VALUES "
                "(1, '2027-01-01', '2027-01-01', :uid, gen_random_uuid())"
            ),
            {"uid": super_admin.id},
        )
    db.rollback()


def test_renewal_leaves_user_accounts_unchanged(client, make_user, subscription, db):
    make_user(AccessCategory.COMPANY_ADMIN)
    _signed_in_super(client, make_user)

    def snapshot():
        db.expire_all()
        return [
            (u.id, u.email, u.password_hash, u.access_category, u.is_active, u.full_name)
            for u in db.scalars(select(User).order_by(User.created_at))
        ]

    before = snapshot()
    client.post(RENEW, json=_payload(subscription.expiry_date), headers=csrf_header(client))
    assert snapshot() == before
