"""Shop Allowance: Super Admin control, enforcement, concurrency, privacy."""

import secrets
import threading
import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.core import clock
from app.core.errors import AppError
from app.db.session import get_engine
from app.main import app
from app.models import (
    AccessCategory,
    AppSubscription,
    AuditEvent,
    CompanyRole,
    CompanyRolePermission,
    Shop,
    ShopAllowance,
    User,
)
from app.services import company_users
from app.services import shop_allowance as allowance_svc
from app.services import shops as shop_svc
from tests.conftest import alembic_config, csrf_header, login

SA_URL = "/api/v1/super-admin/shop-allowance"
SHOPS = "/api/v1/company/shops"
COMPANY_URL = f"{SHOPS}/allowance"
DASHBOARD = "/api/v1/company/dashboard/summary"
ORIGIN = {"Origin": "http://localhost:3000"}
SUMMARY_KEYS = {
    "mode",
    "max_shops",
    "registered_shops",
    "available_slots",
    "at_capacity",
    "over_limit",
}
pytestmark = pytest.mark.usefixtures("valid_subscription")


def h(client: TestClient) -> dict[str, str]:
    return {**csrf_header(client), **ORIGIN}


def signed_in(make_user, category: AccessCategory, email: str | None = None) -> TestClient:
    address, password = make_user(category, email=email)
    client = TestClient(app, base_url="https://testserver")
    assert login(client, address, password).status_code == 200
    return client


@pytest.fixture
def sa(make_user) -> TestClient:
    return signed_in(make_user, AccessCategory.SUPER_ADMIN, "root@example.test")


@pytest.fixture
def admin(make_user) -> TestClient:
    return signed_in(make_user, AccessCategory.COMPANY_ADMIN, "owner@example.test")


def staff(db: Session, make_user, permissions: list[str]) -> TestClient:
    role = CompanyRole(name=f"Role {secrets.token_hex(3)}", is_active=True, version=1)
    role.permissions = [
        CompanyRolePermission(permission=p) for p in {"dashboard.view", *permissions}
    ]
    db.add(role)
    db.commit()
    email, password = make_user(AccessCategory.COMPANY_USER)
    db.execute(update(User).where(User.email == email).values(company_role_id=role.id))
    db.commit()
    client = TestClient(app, base_url="https://testserver")
    assert login(client, email, password).status_code == 200
    return client


def set_allowance(sa: TestClient, mode: str, max_shops: int | None = None):
    version = sa.get(SA_URL).json()["version"]
    return sa.put(
        SA_URL,
        json={"mode": mode, "max_shops": max_shops, "expected_version": version},
        headers=h(sa),
    )


_counter = iter(range(1, 10_000))


def create(client: TestClient, **overrides: object):
    n = next(_counter)
    data: dict[str, object] = {
        "name": f"Shop {n}",
        "branch_name": "Branch",
        "code": f"C{n}",
        "pos_id": f"P{n}",
    }
    data.update(overrides)
    return client.post(SHOPS, json=data, headers=h(client))


def registered(db: Session) -> int:
    db.expire_all()
    return int(db.scalar(select(func.count()).select_from(Shop)) or 0)


def owner(db: Session) -> User:
    return db.scalar(select(User).where(User.email == "owner@example.test"))  # type: ignore[return-value]


def raw_shop(db: Session, code: str) -> None:
    db.execute(
        text("INSERT INTO shops (name, branch_name, code, pos_id) VALUES ('Raw', 'B', :c, :c)"),
        {"c": code},
    )


# --- Migration and initial state ------------------------------------------------------


def test_migration_preserves_existing_shops_and_starts_unlimited(db: Session) -> None:
    cfg = alembic_config()
    command.downgrade(cfg, "0008_shops")
    try:
        db.execute(
            text(
                "INSERT INTO shops (name, branch_name, code, pos_id, encrypted_fbr_token, "
                "fbr_token_updated_at, is_active) VALUES "
                "('Old A', 'Gulberg', 'OLD-A', '000501', 'v1:test:ciphertext-a', now(), true), "
                "('Old B', 'DHA', 'OLD-B', '000502', NULL, NULL, false)"
            )
        )
        db.commit()
        fingerprint = "SELECT string_agg(row(s.*)::text, '|' ORDER BY code) FROM shops s"
        before = db.scalar(text(fingerprint))
    finally:
        command.upgrade(cfg, "head")
    assert db.scalar(text(fingerprint)) == before  # rows, tokens, statuses untouched
    row = db.get(ShopAllowance, 1)
    assert row is not None and (row.mode, row.max_shops, row.version) == ("unlimited", None, 1)
    usage = allowance_svc.get_usage(db)
    assert (usage.registered, usage.available, usage.updated_at) == (2, None, None)


def test_initial_state_is_unlimited(sa: TestClient) -> None:
    data = sa.get(SA_URL).json()
    assert data == {
        "mode": "unlimited",
        "max_shops": None,
        "registered_shops": 0,
        "available_slots": None,
        "at_capacity": False,
        "over_limit": False,
        "version": 1,
        "last_updated_at": None,
    }


# --- Configuration and validation -------------------------------------------------------


def test_configure_finite_allowance_is_audited(
    sa: TestClient, admin: TestClient, db: Session
) -> None:
    create(admin)
    res = set_allowance(sa, "limited", 5)
    assert res.status_code == 200
    body = res.json()
    assert body["changed"] is True
    assert body["allowance"]["mode"] == "limited" and body["allowance"]["max_shops"] == 5
    assert body["allowance"]["registered_shops"] == 1
    assert body["allowance"]["available_slots"] == 4
    assert body["allowance"]["version"] == 2 and body["allowance"]["last_updated_at"]
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "shop_allowance.changed"))
    assert event is not None
    root = db.scalar(select(User).where(User.email == "root@example.test"))
    assert event.actor == f"user:{root.id}"  # type: ignore[union-attr]
    assert event.details == {
        "previous_mode": "unlimited",
        "previous_max_shops": None,
        "new_mode": "limited",
        "new_max_shops": 5,
        "registered_shops": 1,
        "version": 2,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"mode": "limited", "max_shops": 0},
        {"mode": "limited", "max_shops": -1},
        {"mode": "limited", "max_shops": 5.5},
        {"mode": "limited", "max_shops": 5.0},
        {"mode": "limited", "max_shops": "5"},
        {"mode": "limited", "max_shops": True},
        {"mode": "limited", "max_shops": None},
        {"mode": "limited"},
        {"mode": "limited", "max_shops": allowance_svc.MAX_LIMIT + 1},
        {"mode": "unlimited", "max_shops": 999999},
        {"mode": "unlimited", "max_shops": 0},
        {"mode": "infinite", "max_shops": None},
        {"mode": "limited", "max_shops": 5, "extra": 1},
    ],
)
def test_invalid_allowances_are_rejected(sa: TestClient, db: Session, payload: dict) -> None:
    res = sa.put(SA_URL, json={**payload, "expected_version": 1}, headers=h(sa))
    assert res.status_code == 422
    row = db.get(ShopAllowance, 1)
    assert row is not None and (row.mode, row.max_shops, row.version) == ("unlimited", None, 1)


def test_missing_expected_version_is_rejected(sa: TestClient) -> None:
    assert (
        sa.put(SA_URL, json={"mode": "limited", "max_shops": 3}, headers=h(sa)).status_code == 422
    )


def test_database_rejects_inconsistent_settings(db: Session) -> None:
    for values in (
        "mode = 'limited', max_shops = NULL",
        "mode = 'limited', max_shops = 0",
        "mode = 'unlimited', max_shops = 5",
        "mode = 'other', max_shops = NULL",
    ):
        with pytest.raises(Exception, match="ck_shop_allowance_mode"):
            db.execute(text(f"UPDATE shop_allowance SET {values}"))
        db.rollback()
    with pytest.raises(Exception, match="ck_shop_allowance_singleton"):
        db.execute(text("INSERT INTO shop_allowance (id, mode) VALUES (2, 'unlimited')"))
    db.rollback()
    with pytest.raises(Exception, match="cannot be deleted"):
        db.execute(text("DELETE FROM shop_allowance"))
    db.rollback()


def test_stale_form_and_duplicate_submission(sa: TestClient, db: Session) -> None:
    first = sa.put(
        SA_URL, json={"mode": "limited", "max_shops": 5, "expected_version": 1}, headers=h(sa)
    )
    assert first.status_code == 200 and first.json()["changed"] is True
    # The same submission again (double click / retry): unchanged, no second audit.
    again = sa.put(
        SA_URL, json={"mode": "limited", "max_shops": 5, "expected_version": 1}, headers=h(sa)
    )
    assert again.status_code == 200 and again.json()["changed"] is False
    assert again.json()["allowance"]["version"] == 2
    # A different value from a form opened before the change: stale.
    stale = sa.put(
        SA_URL, json={"mode": "limited", "max_shops": 9, "expected_version": 1}, headers=h(sa)
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "stale_shop_allowance"
    events = db.scalars(select(AuditEvent).where(AuditEvent.action == "shop_allowance.changed"))
    assert len(list(events)) == 1
    assert db.get(ShopAllowance, 1).max_shops == 5  # type: ignore[union-attr]


# --- Enforcement --------------------------------------------------------------------------


def test_unlimited_mode_never_blocks_on_count(
    sa: TestClient, admin: TestClient, db: Session
) -> None:
    for _ in range(12):
        assert create(admin).status_code == 201
    assert registered(db) == 12
    data = sa.get(SA_URL).json()
    assert data["available_slots"] is None and data["at_capacity"] is False


def test_full_capacity_rejects_creation(sa: TestClient, admin: TestClient, db: Session) -> None:
    assert set_allowance(sa, "limited", 2).status_code == 200
    assert create(admin).status_code == 201
    assert create(admin).status_code == 201
    res = create(admin)
    assert res.status_code == 409 and res.json()["error"]["code"] == "shop_limit_reached"
    assert "Super Admin" in res.json()["error"]["message"]
    assert registered(db) == 2
    company = admin.get(COMPANY_URL).json()
    assert company == {
        "mode": "limited",
        "max_shops": 2,
        "registered_shops": 2,
        "available_slots": 0,
        "at_capacity": True,
        "over_limit": False,
    }


def test_inactive_shops_count_and_deactivation_frees_nothing(
    sa: TestClient, admin: TestClient, db: Session
) -> None:
    assert set_allowance(sa, "limited", 2).status_code == 200
    first = create(admin).json()
    create(admin)
    res = admin.post(
        f"{SHOPS}/{first['id']}/deactivate", json={"expected_version": 1}, headers=h(admin)
    )
    assert res.status_code == 200
    blocked = create(admin)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "shop_limit_reached"
    summary = admin.get(SHOPS).json()
    assert summary["summary"] == {"total": 2, "active": 1, "inactive": 1}
    assert summary["allowance"]["registered_shops"] == 2
    assert summary["allowance"]["available_slots"] == 0
    # Reactivation inserts nothing, so it is allowed at full capacity.
    back = admin.post(
        f"{SHOPS}/{first['id']}/reactivate", json={"expected_version": 2}, headers=h(admin)
    )
    assert back.status_code == 200 and back.json()["status"] == "active"
    assert registered(db) == 2


def test_example_limit_five_with_one_inactive(sa: TestClient, admin: TestClient) -> None:
    assert set_allowance(sa, "limited", 5).status_code == 200
    ids = [create(admin).json()["id"] for _ in range(4)]
    admin.post(f"{SHOPS}/{ids[0]}/deactivate", json={"expected_version": 1}, headers=h(admin))
    data = sa.get(SA_URL).json()
    assert (data["registered_shops"], data["available_slots"]) == (4, 1)


def test_reduction_below_usage_keeps_shops_and_blocks_creation(
    sa: TestClient, admin: TestClient, db: Session
) -> None:
    shops = [create(admin).json() for _ in range(3)]
    snapshot = "SELECT string_agg(row(s.*)::text, '|' ORDER BY code) FROM shops s"
    before = db.scalar(text(snapshot))
    res = set_allowance(sa, "limited", 2)
    assert res.status_code == 200
    data = res.json()["allowance"]
    assert (data["registered_shops"], data["max_shops"], data["available_slots"]) == (3, 2, 0)
    assert data["over_limit"] is True and data["at_capacity"] is True
    assert db.scalar(text(snapshot)) == before  # nothing deactivated, deleted or edited
    edit = admin.patch(
        f"{SHOPS}/{shops[0]['id']}",
        json={"expected_version": 1, "name": "Renamed"},
        headers=h(admin),
    )
    assert edit.status_code == 200
    assert create(admin).json()["error"]["code"] == "shop_limit_reached"
    assert len(admin.get(SHOPS).json()["items"]) == 3


def test_increase_after_capacity_allows_creation(sa: TestClient, admin: TestClient) -> None:
    assert set_allowance(sa, "limited", 1).status_code == 200
    assert create(admin).status_code == 201
    assert create(admin).status_code == 409
    assert set_allowance(sa, "limited", 2).status_code == 200
    assert create(admin).status_code == 201
    assert create(admin).status_code == 409


def test_switch_limited_to_unlimited(sa: TestClient, admin: TestClient, db: Session) -> None:
    assert set_allowance(sa, "limited", 1).status_code == 200
    create(admin)
    assert create(admin).status_code == 409
    res = set_allowance(sa, "unlimited")
    assert res.status_code == 200 and res.json()["allowance"]["max_shops"] is None
    assert create(admin).status_code == 201
    event = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.action == "shop_allowance.changed")
        .order_by(AuditEvent.occurred_at.desc())
    ).first()
    assert event is not None and event.details["previous_mode"] == "limited"
    assert event.details["previous_max_shops"] == 1 and event.details["new_max_shops"] is None


def test_uniqueness_rules_still_apply(sa: TestClient, admin: TestClient) -> None:
    assert set_allowance(sa, "limited", 5).status_code == 200
    assert create(admin, code="LHR-01", pos_id="000123").status_code == 201
    dup_code = create(admin, code="lhr-01")
    assert dup_code.status_code == 409 and dup_code.json()["error"]["code"] == "shop_code_taken"
    dup_pos = create(admin, pos_id="000123")
    assert dup_pos.status_code == 409 and dup_pos.json()["error"]["code"] == "pos_id_taken"


# --- Database-level safeguard --------------------------------------------------------------


def test_trigger_blocks_raw_inserts_beyond_the_allowance(db: Session) -> None:
    raw_shop(db, "R1")
    raw_shop(db, "R2")
    db.commit()
    db.execute(text("UPDATE shop_allowance SET mode = 'limited', max_shops = 2"))
    db.commit()
    with pytest.raises(Exception, match="shop_limit_reached"):
        raw_shop(db, "R3")
    db.rollback()
    db.execute(text("UPDATE shop_allowance SET mode = 'unlimited', max_shops = NULL"))
    db.commit()
    raw_shop(db, "R3")
    db.commit()
    assert registered(db) == 3


def test_trigger_error_maps_to_the_typed_conflict(
    admin: TestClient, db: Session, monkeypatch
) -> None:
    """If the service check were bypassed, the trigger still answers 409 shop_limit_reached."""
    db.execute(text("UPDATE shop_allowance SET mode = 'limited', max_shops = 1"))
    db.commit()
    create(admin)
    monkeypatch.setattr(allowance_svc, "ensure_capacity", lambda _db: None)
    res = create(admin)
    assert res.status_code == 409 and res.json()["error"]["code"] == "shop_limit_reached"
    assert registered(db) == 1


# --- Concurrency -----------------------------------------------------------------------------


def _create_via_service(factory, actor_id, n: int) -> str:
    with factory() as session:
        try:
            shop_svc.create_shop(
                session,
                actor=session.get(User, actor_id),
                name=f"Race {n}",
                branch_name="B",
                code=f"RACE-{n}",
                pos_id=f"RACE-{n}",
                fbr_token=None,
            )
            return "created"
        except AppError as exc:
            return exc.code


def test_concurrent_creates_cannot_exceed_the_limit(
    sa: TestClient, admin: TestClient, db: Session
) -> None:
    assert set_allowance(sa, "limited", 5).status_code == 200
    for _ in range(4):
        assert create(admin).status_code == 201
    actor_id = owner(db).id
    factory = sessionmaker(bind=get_engine(), autoflush=False)
    barrier = threading.Barrier(5)
    outcomes: list[str] = []

    def worker(n: int) -> None:
        barrier.wait()
        outcomes.append(_create_via_service(factory, actor_id, n))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(outcomes) == ["created"] + ["shop_limit_reached"] * 4
    assert registered(db) == 5


def test_allowance_change_waits_for_an_in_flight_creation(
    sa: TestClient, admin: TestClient, db: Session
) -> None:
    assert set_allowance(sa, "limited", 3).status_code == 200
    create(admin)
    create(admin)
    actor = owner(db)
    root = db.scalar(select(User).where(User.email == "root@example.test"))
    factory = sessionmaker(bind=get_engine(), autoflush=False)
    creator = factory()
    allowance_svc.ensure_capacity(creator)  # holds the allowance lock
    creator.add(Shop(name="In flight", branch_name="B", code="FLIGHT", pos_id="FLIGHT"))
    creator.flush()
    result: dict[str, object] = {}

    def lower_limit() -> None:
        with factory() as session:
            usage, changed = allowance_svc.update_allowance(
                session,
                actor=session.get(User, root.id),
                mode="limited",
                max_shops=2,
                expected_version=2,  # type: ignore[union-attr]
            )
            result["usage"] = usage

    thread = threading.Thread(target=lower_limit)
    thread.start()
    time.sleep(0.5)
    assert thread.is_alive()  # blocked on the allowance lock
    creator.commit()
    creator.close()
    thread.join(timeout=10)
    usage = result["usage"]
    assert usage.registered == 3 and usage.max_shops == 2 and usage.over_limit  # type: ignore[attr-defined]
    assert actor is not None and registered(db) == 3


def test_creation_waits_for_an_in_flight_allowance_change(
    sa: TestClient, admin: TestClient, db: Session
) -> None:
    create(admin)
    create(admin)
    actor_id = owner(db).id
    factory = sessionmaker(bind=get_engine(), autoflush=False)
    changer = factory()
    row = changer.scalar(select(ShopAllowance).with_for_update())
    assert row is not None
    row.mode, row.max_shops, row.version = "limited", 2, row.version + 1
    changer.flush()
    outcome: list[str] = []
    thread = threading.Thread(
        target=lambda: outcome.append(_create_via_service(factory, actor_id, 99))
    )
    thread.start()
    time.sleep(0.5)
    assert thread.is_alive()  # waiting for the allowance change to commit
    changer.commit()
    changer.close()
    thread.join(timeout=10)
    assert outcome == ["shop_limit_reached"]
    assert registered(db) == 2


# --- Authorization and privacy -----------------------------------------------------------------


def test_unauthenticated_requests_are_rejected(client: TestClient) -> None:
    assert client.get(SA_URL).status_code == 401
    assert client.put(SA_URL, json={"mode": "unlimited", "expected_version": 1}).status_code == 401
    assert client.get(COMPANY_URL).status_code == 401


def test_company_accounts_cannot_change_the_allowance(
    admin: TestClient, db: Session, make_user
) -> None:
    everything = [
        "shops.view",
        "shops.create",
        "shops.edit",
        "shops.delete",
        "shops.manage_integration",
        "users.view",
        "users.create",
        "users.edit",
        "roles.manage",
    ]
    power_user = staff(db, make_user, everything)
    for client in (admin, power_user):
        assert client.get(SA_URL).status_code == 403
        res = client.put(
            SA_URL, json={"mode": "unlimited", "expected_version": 1}, headers=h(client)
        )
        assert res.status_code == 403
        for method in ("put", "post", "patch", "delete"):
            # No write route exists (405), or "allowance" is not a shop ID (422).
            res = getattr(client, method)(COMPANY_URL, headers=h(client))
            assert res.status_code in (405, 422)
    assert db.get(ShopAllowance, 1).version == 1  # type: ignore[union-attr]


def test_company_read_requires_shops_view(admin: TestClient, db: Session, make_user) -> None:
    assert admin.get(COMPANY_URL).status_code == 200
    viewer = staff(db, make_user, ["shops.view"])
    data = viewer.get(COMPANY_URL).json()
    assert set(data) == SUMMARY_KEYS
    outsider = staff(db, make_user, [])
    assert outsider.get(COMPANY_URL).status_code == 403


def test_super_admin_cannot_use_company_shop_endpoints(sa: TestClient) -> None:
    assert sa.get(COMPANY_URL).status_code == 403
    assert sa.get(SHOPS).status_code == 403


def test_csrf_and_foreign_origin_are_required(sa: TestClient, db: Session) -> None:
    payload = {"mode": "limited", "max_shops": 3, "expected_version": 1}
    no_token = sa.put(SA_URL, json=payload, headers=ORIGIN)
    assert no_token.status_code == 403 and no_token.json()["error"]["code"] == "csrf_failed"
    foreign = sa.put(
        SA_URL, json=payload, headers={**csrf_header(sa), "Origin": "https://evil.test"}
    )
    assert foreign.status_code == 403
    assert db.get(ShopAllowance, 1).version == 1  # type: ignore[union-attr]


def test_expired_subscription(sa: TestClient, admin: TestClient, db: Session) -> None:
    today = clock.utcnow().date()
    db.execute(
        update(AppSubscription).values(
            start_date=today - timedelta(days=400), expiry_date=today - timedelta(days=1)
        )
    )
    db.commit()
    res = admin.get(COMPANY_URL)
    assert res.status_code == 403 and res.json()["error"]["code"] == "subscription_expired"
    assert sa.get(SA_URL).status_code == 200
    assert set_allowance(sa, "limited", 4).status_code == 200  # still manageable after expiry


def test_aggregate_responses_never_contain_shop_details(
    sa: TestClient, admin: TestClient, db: Session
) -> None:
    secret_token = "QA-TOKEN-" + secrets.token_hex(16)
    shop = create(
        admin,
        name="Zebra Private Name",
        branch_name="Hidden Branch Street",
        code="SECRET-CODE",
        pos_id="POS-98765",
        fbr_token=secret_token,
    ).json()
    ciphertext = db.scalar(select(Shop.encrypted_fbr_token))
    texts = [sa.get(SA_URL).text, set_allowance(sa, "limited", 7).text]
    texts += [admin.get(COMPANY_URL).text, admin.get(DASHBOARD).json()["shop_allowance"].__repr__()]
    audit = " ".join(
        str(d)
        for d in db.scalars(
            select(AuditEvent.details).where(AuditEvent.action == "shop_allowance.changed")
        )
    )
    for needle in (
        "Zebra Private Name",
        "Hidden Branch Street",
        "SECRET-CODE",
        "POS-98765",
        secret_token,
        ciphertext,
        shop["id"],
    ):
        assert all(needle not in t for t in texts), needle
        assert needle not in audit, needle
    assert set(sa.get(SA_URL).json()) == SUMMARY_KEYS | {"version", "last_updated_at"}


# --- Company integration --------------------------------------------------------------------------


def test_shop_page_and_dashboard_report_the_allowance(sa: TestClient, admin: TestClient) -> None:
    create(admin)
    create(admin)
    page = admin.get(SHOPS).json()
    assert page["allowance"]["mode"] == "unlimited" and page["allowance"]["registered_shops"] == 2
    dash = admin.get(DASHBOARD).json()
    assert dash["shop_allowance"]["mode"] == "unlimited"
    assert dash["metrics"]["total_shops"]["value"] == 2
    assert set_allowance(sa, "limited", 10).status_code == 200
    dash = admin.get(DASHBOARD).json()["shop_allowance"]
    assert (dash["registered_shops"], dash["max_shops"], dash["available_slots"]) == (2, 10, 8)


def test_user_account_limit_is_unchanged() -> None:
    assert company_users.MAX_ACTIVE_COMPANY_ACCOUNTS == 15
