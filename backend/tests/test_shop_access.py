"""User shop access (Phase 3.3): assignment management and shop-level authorization."""

import secrets
import threading
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Column, MetaData, Numeric, Table, select, text, update
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session

from alembic import command
from app.core import clock
from app.core.errors import AppError
from app.main import app
from app.models import (
    AccessCategory,
    AppSubscription,
    AuditEvent,
    CompanyRole,
    CompanyRolePermission,
    Shop,
    User,
    UserShopAccess,
    UserShopAssignment,
)
from app.services import shop_access as access_svc
from app.services import shop_context as ctx_svc
from app.services import shops as shop_svc
from tests.conftest import alembic_config, csrf_header, login

USERS = "/api/v1/company/users"
OPTIONS = "/api/v1/company/shop-options"
ASSIGNABLE = "/api/v1/company/shop-assignment-options"
ORIGIN = {"Origin": "http://localhost:3000"}
EVERY_ASSIGNABLE = [
    "shops.view",
    "shops.create",
    "shops.edit",
    "shops.delete",
    "shops.manage_integration",
    "uploads.view",
    "uploads.upload",
    "uploads.edit_draft",
    "uploads.delete_draft",
    "uploads.submit",
    "approvals.view",
    "approvals.decide",
    "fbr_sync.view",
    "fbr_sync.control",
    "fbr_sync.retry",
    "reports.view",
    "reports.export",
]
pytestmark = pytest.mark.usefixtures("valid_subscription")


def h(client: TestClient) -> dict[str, str]:
    return {**csrf_header(client), **ORIGIN}


def signed_in(make_user, category: AccessCategory, email: str | None = None) -> TestClient:
    address, password = make_user(category, email=email)
    client = TestClient(app, base_url="https://testserver")
    assert login(client, address, password).status_code == 200
    return client


@pytest.fixture
def admin(make_user) -> TestClient:
    return signed_in(make_user, AccessCategory.COMPANY_ADMIN, "owner@example.test")


@pytest.fixture
def uploads_consumer(monkeypatch) -> None:
    """Pretend Excel Uploads is built, so Company Users get a shop context (future module)."""
    monkeypatch.setattr(
        ctx_svc,
        "CONSUMERS",
        (ctx_svc.Consumer("uploads", implemented=True, permission="uploads.view"),),
    )


class Staff:
    def __init__(self, client: TestClient, user_id: uuid.UUID, role_id: uuid.UUID) -> None:
        self.client, self.id, self.role_id = client, user_id, role_id


def staff(
    db: Session, make_user, permissions: list[str], *, mode: str = "none", shops: list[Shop] = ()
) -> Staff:  # type: ignore[assignment]
    role = CompanyRole(name=f"Role {secrets.token_hex(3)}", is_active=True, version=1)
    role.permissions = [
        CompanyRolePermission(permission=p) for p in {"dashboard.view", *permissions}
    ]
    db.add(role)
    db.commit()
    email, password = make_user(AccessCategory.COMPANY_USER)
    user = db.scalar(select(User).where(User.email == email))
    assert user is not None
    user.company_role_id = role.id
    db.add(UserShopAccess(user_id=user.id, access_mode=mode, version=1))
    db.flush()
    for s in shops:
        db.add(UserShopAssignment(user_id=user.id, shop_id=s.id))
    db.commit()
    client = TestClient(app, base_url="https://testserver")
    assert login(client, email, password).status_code == 200
    return Staff(client, user.id, role.id)


def add_shop(db: Session, name: str, code: str, *, active: bool = True) -> Shop:
    shop = Shop(
        name=name, branch_name="Secret Branch", code=code, pos_id=f"POS{code}", is_active=active
    )
    db.add(shop)
    db.commit()
    return shop


def owner(db: Session) -> User:
    return db.scalar(select(User).where(User.email == "owner@example.test"))  # type: ignore[return-value]


def fresh(db: Session, user_id: uuid.UUID) -> User:
    db.expire_all()
    return db.get(User, user_id)  # type: ignore[return-value]


def put_access(
    admin: TestClient,
    user_id: uuid.UUID,
    mode: str,
    shops: list[Shop] = (),
    version: int | None = None,
):  # type: ignore[assignment]
    if version is None:
        version = admin.get(f"{USERS}/{user_id}/shop-access").json()["version"]
    return admin.put(
        f"{USERS}/{user_id}/shop-access",
        json={"mode": mode, "shop_ids": [str(s.id) for s in shops], "expected_version": version},
        headers=h(admin),
    )


def option_codes(client: TestClient) -> list[str]:
    return [i["code"] for i in client.get(OPTIONS).json()["items"]]


# Hypothetical future operational records (e.g. sales invoices), to prove that
# consolidated queries are filtered inside SQL.
FUTURE = Table(
    "qa_future_sales",
    MetaData(),
    Column("shop_id", UUID(as_uuid=True), nullable=False),
    Column("amount", Numeric(14, 2), nullable=False),
)


def create_future_sales(db: Session) -> None:
    """Temp table on the session's current connection: call after all setup commits."""
    db.execute(
        text(
            "CREATE TEMP TABLE qa_future_sales "
            "(shop_id uuid NOT NULL, amount numeric(14,2) NOT NULL) ON COMMIT DROP"
        )
    )


def sales_for(db: Session, user: User, context: ctx_svc.ShopContext) -> list[uuid.UUID]:
    rows = db.execute(
        select(FUTURE.c.shop_id).where(ctx_svc.scope_filter(user, context, FUTURE.c.shop_id))
    ).all()
    return sorted(r.shop_id for r in rows)


# --- Migration and defaults ------------------------------------------------------------------


def test_migration_gives_existing_company_users_no_shop_access(db: Session, make_user) -> None:
    cfg = alembic_config()
    command.downgrade(cfg, "0009_shop_allowance")
    try:
        make_user(AccessCategory.COMPANY_ADMIN, email="legacy-admin@example.test")
        make_user(AccessCategory.COMPANY_USER, email="legacy-user@example.test")
        make_user(AccessCategory.SUPER_ADMIN, email="legacy-root@example.test")
    finally:
        command.upgrade(cfg, "head")
    rows = dict(
        db.execute(
            text(
                "SELECT u.email, a.access_mode FROM users u "
                "LEFT JOIN user_shop_access a ON a.user_id = u.id"
            )
        ).all()
    )
    assert rows == {
        "legacy-user@example.test": "none",
        "legacy-admin@example.test": None,  # tier scope, no editable row
        "legacy-root@example.test": None,
    }
    assert db.scalar(text("SELECT count(*) FROM user_shop_assignments")) == 0


def test_new_users_default_to_no_shop_access(admin: TestClient, db: Session) -> None:
    role = db.scalar(select(CompanyRole).where(CompanyRole.system_key == "company_user"))
    res = admin.post(
        USERS,
        json={"full_name": "New Person", "email": "new@example.test", "role_id": str(role.id)},
        headers=h(admin),
    )  # type: ignore[union-attr]
    assert res.status_code == 201
    assert res.json()["user"]["shop_access"] == {"mode": "none", "shop_count": None}
    row = db.get(UserShopAccess, uuid.UUID(res.json()["user"]["id"]))
    assert row is not None and row.access_mode == "none"


def test_create_user_with_selected_shops(admin: TestClient, db: Session) -> None:
    a = add_shop(db, "Cheena Main Shop", "CH-001")
    add_shop(db, "Cheena Main Shop", "CH-002")
    role = db.scalar(select(CompanyRole).where(CompanyRole.system_key == "company_user"))
    res = admin.post(
        USERS,
        json={
            "full_name": "Hamza",
            "email": "hamza@example.test",
            "role_id": str(role.id),  # type: ignore[union-attr]
            "shop_access": {"mode": "selected", "shop_ids": [str(a.id)]},
        },
        headers=h(admin),
    )
    assert res.status_code == 201
    user_id = res.json()["user"]["id"]
    assert res.json()["user"]["shop_access"] == {"mode": "selected", "shop_count": 1}
    detail = admin.get(f"{USERS}/{user_id}/shop-access").json()
    assert [s["code"] for s in detail["shops"]] == ["CH-001"]  # duplicate name, right shop
    event = db.scalar(
        select(AuditEvent).where(AuditEvent.action == "company_user.shop_access_changed")
    )
    assert event is not None and event.details["new_shop_ids"] == [str(a.id)]


@pytest.mark.parametrize(
    "access",
    [
        {"mode": "selected", "shop_ids": []},
        {"mode": "all", "shop_ids": ["00000000-0000-4000-8000-000000000001"]},
        {"mode": "selected", "shop_ids": ["00000000-0000-4000-8000-000000000001"]},  # unknown shop
        {"mode": "everything", "shop_ids": []},
        {"mode": "none", "extra": True},
    ],
)
def test_create_user_rejects_bad_shop_access(admin: TestClient, db: Session, access: dict) -> None:
    role = db.scalar(select(CompanyRole).where(CompanyRole.system_key == "company_user"))
    res = admin.post(
        USERS,
        json={
            "full_name": "X Y",
            "email": f"{secrets.token_hex(3)}@example.test",
            "role_id": str(role.id),
            "shop_access": access,
        },
        headers=h(admin),
    )  # type: ignore[union-attr]
    assert res.status_code == 422
    assert db.scalar(select(User).where(User.full_name == "X Y")) is None  # atomic: no user either


# --- Management API ----------------------------------------------------------------------------


def test_admin_manages_assignments_and_audit_is_accurate(
    admin: TestClient, db: Session, make_user
) -> None:
    a, b, c = add_shop(db, "A", "A-1"), add_shop(db, "B", "B-1"), add_shop(db, "C", "C-1")
    user = staff(db, make_user, [])
    res = put_access(admin, user.id, "selected", [a, b])
    assert res.status_code == 200 and res.json()["changed"] is True
    body = res.json()["access"]
    assert body["mode"] == "selected" and body["shop_count"] == 2 and body["version"] == 2
    res = put_access(admin, user.id, "selected", [b, c])
    events = list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.action == "company_user.shop_access_changed")
            .order_by(AuditEvent.occurred_at)
        )
    )
    assert len(events) == 2
    last = events[-1]
    assert last.actor == f"user:{owner(db).id}" and last.target_user_id == user.id
    assert last.details == {
        "previous_mode": "selected",
        "new_mode": "selected",
        "previous_shop_ids": sorted([str(a.id), str(b.id)]),
        "new_shop_ids": sorted([str(b.id), str(c.id)]),
        "added": 1,
        "removed": 1,
        "version": 3,
    }
    assert put_access(admin, user.id, "all").json()["access"] == {
        "mode": "all",
        "shop_count": None,
        "shops": [],
        "editable": True,
        "version": 4,
        "updated_at": admin.get(f"{USERS}/{user.id}/shop-access").json()["updated_at"],
    }
    assert (
        db.scalar(select(UserShopAssignment).where(UserShopAssignment.user_id == user.id)) is None
    )
    assert put_access(admin, user.id, "none").status_code == 200


def test_no_op_save_writes_no_audit(admin: TestClient, db: Session, make_user) -> None:
    a = add_shop(db, "A", "A-1")
    user = staff(db, make_user, [])
    assert put_access(admin, user.id, "selected", [a], version=1).json()["changed"] is True
    again = put_access(admin, user.id, "selected", [a], version=1)  # double submit, old version
    assert again.status_code == 200 and again.json()["changed"] is False
    assert again.json()["access"]["version"] == 2
    count = db.scalar(
        select(text("count(*)"))
        .select_from(AuditEvent)
        .where(AuditEvent.action == "company_user.shop_access_changed")
    )
    assert count == 1


def test_stale_form_is_a_conflict(admin: TestClient, db: Session, make_user) -> None:
    a, b = add_shop(db, "A", "A-1"), add_shop(db, "B", "B-1")
    user = staff(db, make_user, [])
    assert put_access(admin, user.id, "selected", [a], version=1).status_code == 200
    stale = put_access(admin, user.id, "selected", [b], version=1)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_shop_access"
    detail = admin.get(f"{USERS}/{user.id}/shop-access").json()
    assert [s["code"] for s in detail["shops"]] == ["A-1"]


def test_concurrent_updates_are_serialized(admin: TestClient, db: Session, make_user) -> None:
    a = add_shop(db, "A", "A-1")
    user = staff(db, make_user, [])
    barrier = threading.Barrier(4)
    results: list[int] = []
    bodies = [
        {"mode": "selected", "shop_ids": [str(a.id)], "expected_version": 1},
        {"mode": "all", "shop_ids": [], "expected_version": 1},
    ] * 2

    def worker(body: dict) -> None:
        barrier.wait()
        results.append(
            admin.put(f"{USERS}/{user.id}/shop-access", json=body, headers=h(admin)).status_code
        )

    threads = [threading.Thread(target=worker, args=(b,)) for b in bodies]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    # Exactly one change wins; the identical duplicate is a no-op (200), the other mode is stale.
    assert sorted(results) == [200, 200, 409, 409]
    row = db.get(UserShopAccess, user.id)
    db.refresh(row)
    assert row is not None and row.version == 2


def test_protected_company_admin_cannot_be_reassigned(admin: TestClient, db: Session) -> None:
    me = owner(db)
    detail = admin.get(f"{USERS}/{me.id}/shop-access").json()
    assert detail == {
        "mode": "company",
        "shop_count": None,
        "shops": [],
        "editable": False,
        "version": None,
        "updated_at": None,
    }
    res = admin.put(
        f"{USERS}/{me.id}/shop-access",
        json={"mode": "none", "shop_ids": [], "expected_version": 1},
        headers=h(admin),
    )
    assert res.status_code == 403 and res.json()["error"]["code"] == "protected_admin"
    assert db.get(UserShopAccess, me.id) is None


def test_unauthenticated_and_super_admin_are_denied(
    client: TestClient, make_user, db: Session
) -> None:
    some = uuid.uuid4()
    assert client.get(f"{USERS}/{some}/shop-access").status_code == 401
    assert (
        client.put(
            f"{USERS}/{some}/shop-access", json={"mode": "none", "expected_version": 1}
        ).status_code
        == 401
    )
    assert client.get(ASSIGNABLE).status_code == 401
    root = signed_in(make_user, AccessCategory.SUPER_ADMIN)
    assert root.get(f"{USERS}/{some}/shop-access").status_code == 403
    assert (
        root.put(
            f"{USERS}/{some}/shop-access",
            json={"mode": "none", "expected_version": 1},
            headers=h(root),
        ).status_code
        == 403
    )
    assert root.get(ASSIGNABLE).status_code == 403


def test_company_users_cannot_manage_assignments_even_with_every_permission(
    admin: TestClient, db: Session, make_user
) -> None:
    a = add_shop(db, "A", "A-1")
    power = staff(db, make_user, EVERY_ASSIGNABLE, mode="all")
    victim = staff(db, make_user, [])
    for path in (f"{USERS}/{victim.id}/shop-access", f"{USERS}/{power.id}/shop-access", ASSIGNABLE):
        assert power.client.get(path).status_code == 403
    for target in (victim.id, power.id):
        res = power.client.put(
            f"{USERS}/{target}/shop-access",
            json={"mode": "selected", "shop_ids": [str(a.id)], "expected_version": 1},
            headers=h(power.client),
        )
        assert res.status_code == 403
    assert db.get(UserShopAccess, victim.id).access_mode == "none"  # type: ignore[union-attr]


def test_csrf_and_foreign_origin_are_required(admin: TestClient, db: Session, make_user) -> None:
    user = staff(db, make_user, [])
    body = {"mode": "all", "shop_ids": [], "expected_version": 1}
    no_token = admin.put(f"{USERS}/{user.id}/shop-access", json=body, headers=ORIGIN)
    assert no_token.status_code == 403 and no_token.json()["error"]["code"] == "csrf_failed"
    foreign = admin.put(
        f"{USERS}/{user.id}/shop-access",
        json=body,
        headers={**csrf_header(admin), "Origin": "https://evil.test"},
    )
    assert foreign.status_code == 403
    assert db.get(UserShopAccess, user.id).access_mode == "none"  # type: ignore[union-attr]


def test_expired_subscription_blocks_management_and_operations(
    admin: TestClient, db: Session, make_user, uploads_consumer
) -> None:
    user = staff(db, make_user, ["uploads.view"], mode="all")
    today = clock.utcnow().date()
    db.execute(
        update(AppSubscription).values(
            start_date=today - timedelta(days=400), expiry_date=today - timedelta(days=1)
        )
    )
    db.commit()
    for res in (
        admin.put(
            f"{USERS}/{user.id}/shop-access",
            json={"mode": "none", "shop_ids": [], "expected_version": 1},
            headers=h(admin),
        ),
        user.client.get(OPTIONS),
    ):
        assert res.status_code == 403 and res.json()["error"]["code"] == "subscription_expired"


def test_responses_leak_no_sensitive_shop_fields(
    admin: TestClient, db: Session, make_user, uploads_consumer
) -> None:
    a = add_shop(db, "Leak Test", "LK-1")
    db.execute(
        update(Shop)
        .where(Shop.id == a.id)
        .values(encrypted_fbr_token="v1:test:secretblob", fbr_token_updated_at=clock.utcnow())
    )
    db.commit()
    user = staff(db, make_user, ["uploads.view"], mode="selected", shops=[a])
    bodies = [
        admin.get(f"{USERS}/{user.id}/shop-access").text,
        admin.get(ASSIGNABLE).text,
        admin.get(USERS).text,
        user.client.get(OPTIONS).text,
    ]
    for body in bodies:
        for needle in ("POSLK-1", "Secret Branch", "secretblob", "fbr", "pos_id", "branch"):
            assert needle not in body, needle
    assert set(admin.get(ASSIGNABLE).json()["items"][0]) == {"id", "name", "code", "status"}


# --- Authorization: module permission x shop scope x status x purpose -------------------------


def test_assigned_shop_is_usable_and_unassigned_is_denied(db: Session, make_user) -> None:
    ch1, ch2 = (
        add_shop(db, "Cheena Main Shop", "CH-001"),
        add_shop(db, "Cheena Main Shop", "CH-002"),
    )
    user = staff(db, make_user, ["uploads.upload"], mode="selected", shops=[ch1])
    me = fresh(db, user.id)
    assert (
        ctx_svc.resolve_operational_shop(db, me, str(ch1.id), permission="uploads.upload").shop_id
        == ch1.id
    )
    db.rollback()
    with pytest.raises(AppError) as exc:  # same name, different shop: not assigned
        ctx_svc.resolve_operational_shop(db, me, str(ch2.id), permission="uploads.upload")
    assert exc.value.code == "shop_not_found"


def test_assignment_never_grants_a_missing_module_permission(db: Session, make_user) -> None:
    a = add_shop(db, "A", "A-1")
    user = staff(db, make_user, [], mode="all")
    with pytest.raises(AppError) as exc:
        ctx_svc.resolve_operational_shop(
            db, fresh(db, user.id), str(a.id), permission="approvals.decide"
        )
    assert exc.value.status_code == 403


def test_role_changes_apply_immediately(db: Session, make_user) -> None:
    a = add_shop(db, "A", "A-1")
    user = staff(db, make_user, ["uploads.upload"], mode="all")
    assert ctx_svc.resolve_operational_shop(
        db, fresh(db, user.id), str(a.id), permission="uploads.upload"
    )
    db.rollback()
    db.execute(
        CompanyRolePermission.__table__.delete().where(
            CompanyRolePermission.role_id == user.role_id
        )
    )
    db.commit()
    with pytest.raises(AppError):
        ctx_svc.resolve_operational_shop(
            db, fresh(db, user.id), str(a.id), permission="uploads.upload"
        )


def test_consolidated_reads_are_filtered_in_sql(db: Session, make_user) -> None:
    a, b, c = add_shop(db, "A", "A-1"), add_shop(db, "B", "B-1"), add_shop(db, "C", "C-1")
    selected = staff(db, make_user, ["reports.view"], mode="selected", shops=[b])
    everything = staff(db, make_user, ["reports.view"], mode="all")
    nothing = staff(db, make_user, ["reports.view"], mode="none")
    company_admin = owner_or_admin(db, make_user)
    create_future_sales(db)  # after every setup commit
    for shop in (a, b, c):
        db.execute(FUTURE.insert().values(shop_id=shop.id, amount=100))
    all_ctx = ctx_svc.ALL_SHOPS
    assert sales_for(db, fresh(db, selected.id), all_ctx) == [b.id]  # All Assigned Shops = B only
    assert sales_for(db, fresh(db, everything.id), all_ctx) == sorted([a.id, b.id, c.id])
    assert sales_for(db, fresh(db, nothing.id), all_ctx) == []
    assert sales_for(db, company_admin, all_ctx) == sorted([a.id, b.id, c.id])
    # A forged single-shop context for an unassigned shop still yields nothing.
    forged = ctx_svc.ShopContext(shop=ctx_svc.ShopOption(id=a.id, name="A", code="A-1"))
    assert sales_for(db, fresh(db, selected.id), forged) == []
    ids = set(db.scalars(access_svc.scoped_shop_ids(fresh(db, selected.id))))
    assert ids == {b.id}


def owner_or_admin(db: Session, make_user) -> User:
    email, _ = make_user(AccessCategory.COMPANY_ADMIN)
    return db.scalar(select(User).where(User.email == email))  # type: ignore[return-value]


def test_no_shop_access_sees_nothing(db: Session, make_user, uploads_consumer) -> None:
    a = add_shop(db, "A", "A-1")
    user = staff(db, make_user, ["uploads.view", "uploads.upload"], mode="none")
    data = user.client.get(OPTIONS, params={"selected": str(a.id)}).json()
    assert data["items"] == [] and data["total"] == 0
    assert data["access"] == {"mode": "none", "all_label": "All Assigned Shops"}
    assert data["selection"] == {"status": "not_found", "shop": None}
    with pytest.raises(AppError) as exc:
        ctx_svc.resolve_operational_shop(
            db, fresh(db, user.id), str(a.id), permission="uploads.upload"
        )
    assert exc.value.code == "shop_not_found"
    assert (
        list(db.scalars(access_svc.scoped_shop_ids(fresh(db, user.id), include_inactive=True)))
        == []
    )


def test_selector_lists_only_assigned_active_shops(
    db: Session, make_user, uploads_consumer
) -> None:
    a, b = add_shop(db, "Cheena Main Shop", "CH-001"), add_shop(db, "Cheena Main Shop", "CH-002")
    closed = add_shop(db, "Closed", "CL-1", active=False)
    user = staff(db, make_user, ["uploads.view"], mode="selected", shops=[a, closed])
    data = user.client.get(OPTIONS).json()
    assert [i["code"] for i in data["items"]] == ["CH-001"]
    assert data["access"] == {"mode": "selected", "all_label": "All Assigned Shops"}
    assert (
        user.client.get(OPTIONS, params={"selected": str(b.id)}).json()["selection"]["status"]
        == "not_found"
    )
    assert (
        user.client.get(OPTIONS, params={"selected": str(closed.id)}).json()["selection"]["status"]
        == "inactive"
    )


def test_inactive_shops_block_operations_but_keep_history(
    admin: TestClient, db: Session, make_user
) -> None:
    a = add_shop(db, "A", "A-1")
    user = staff(db, make_user, ["uploads.upload", "reports.view"], mode="selected", shops=[a])
    shop_svc.set_active(db, actor=owner(db), shop_id=a.id, expected_version=1, active=False)
    me = fresh(db, user.id)
    with pytest.raises(AppError) as exc:
        ctx_svc.resolve_operational_shop(db, me, str(a.id), permission="uploads.upload")
    assert exc.value.code == "shop_inactive"
    db.rollback()
    history = ctx_svc.resolve_historical_shop(db, me, str(a.id), permission="reports.view")
    assert history.shop_id == a.id and history.is_active is False
    assert db.get(UserShopAssignment, (user.id, a.id)) is not None  # assignment kept
    assert set(db.scalars(access_svc.scoped_shop_ids(me, include_inactive=True))) == {a.id}
    assert set(db.scalars(access_svc.scoped_shop_ids(me))) == set()
    # Reactivation restores operations because the assignment is still there.
    shop_svc.set_active(db, actor=owner(db), shop_id=a.id, expected_version=2, active=True)
    assert ctx_svc.resolve_operational_shop(
        db, fresh(db, user.id), str(a.id), permission="uploads.upload"
    )


def test_revocation_applies_on_the_next_request(
    admin: TestClient, db: Session, make_user, uploads_consumer
) -> None:
    a, b = add_shop(db, "A", "A-1"), add_shop(db, "B", "B-1")
    user = staff(db, make_user, ["uploads.view"], mode="selected", shops=[a, b])
    assert option_codes(user.client) == ["A-1", "B-1"]
    assert (
        user.client.get(OPTIONS, params={"selected": str(b.id)}).json()["selection"]["status"]
        == "active"
    )
    assert put_access(admin, user.id, "selected", [a]).status_code == 200
    # Same session, no re-login: B is gone and the stale selection is rejected.
    assert option_codes(user.client) == ["A-1"]
    assert user.client.get(OPTIONS, params={"selected": str(b.id)}).json()["selection"] == {
        "status": "not_found",
        "shop": None,
    }
    assert put_access(admin, user.id, "none").status_code == 200
    assert option_codes(user.client) == []


def test_new_shops_reach_all_shops_users_only(
    admin: TestClient, db: Session, make_user, uploads_consumer
) -> None:
    a = add_shop(db, "A", "A-1")
    everything = staff(db, make_user, ["uploads.view"], mode="all")
    selected = staff(db, make_user, ["uploads.view"], mode="selected", shops=[a])
    created = admin.post(
        "/api/v1/company/shops",
        json={
            "name": "Brand New",
            "branch_name": "X",
            "code": "NEW-1",
            "pos_id": "900",
            "sales_tax_rate": "18",
        },
        headers=h(admin),
    )
    assert created.status_code == 201
    assert "NEW-1" in option_codes(everything.client)
    assert "NEW-1" not in option_codes(selected.client)


def test_rename_keeps_the_assignment(
    admin: TestClient, db: Session, make_user, uploads_consumer
) -> None:
    a = add_shop(db, "Before", "RN-1")
    user = staff(db, make_user, ["uploads.view"], mode="selected", shops=[a])
    res = admin.patch(
        f"/api/v1/company/shops/{a.id}",
        json={"expected_version": 1, "name": "After"},
        headers=h(admin),
    )
    assert res.status_code == 200
    item = user.client.get(OPTIONS).json()["items"][0]
    assert item == {"id": str(a.id), "name": "After", "code": "RN-1"}
    assert admin.get(f"{USERS}/{user.id}/shop-access").json()["shops"][0]["name"] == "After"


def test_disabled_users_lose_shop_access(db: Session, make_user, uploads_consumer) -> None:
    add_shop(db, "A", "A-1")
    user = staff(db, make_user, ["uploads.view", "uploads.upload"], mode="all")
    assert option_codes(user.client) == ["A-1"]
    db.execute(update(User).where(User.id == user.id).values(is_active=False))
    db.commit()
    assert user.client.get(OPTIONS).status_code in (401, 403)
    assert list(db.scalars(access_svc.scoped_shop_ids(fresh(db, user.id)))) == []


def test_admin_scope_and_label_are_company_wide(admin: TestClient, db: Session) -> None:
    add_shop(db, "A", "A-1")
    data = admin.get(OPTIONS).json()
    assert data["access"] == {"mode": "company", "all_label": "All Shops"}
    assert [i["code"] for i in data["items"]] == ["A-1"]


def test_shop_management_stays_company_wide(db: Session, make_user) -> None:
    add_shop(db, "A", "A-1")
    add_shop(db, "B", "B-1")
    viewer = staff(db, make_user, ["shops.view"], mode="none")
    assert (
        viewer.client.get("/api/v1/company/shops").json()["total"] == 2
    )  # administrative, unfiltered


def test_user_list_shows_shop_access_summaries(admin: TestClient, db: Session, make_user) -> None:
    a, b = add_shop(db, "A", "A-1"), add_shop(db, "B", "B-1")
    one = staff(db, make_user, [], mode="selected", shops=[a])
    two = staff(db, make_user, [], mode="selected", shops=[a, b])
    everything = staff(db, make_user, [], mode="all")
    nothing = staff(db, make_user, [], mode="none")
    items = {
        i["id"]: i["shop_access"] for i in admin.get(USERS, params={"limit": 50}).json()["items"]
    }
    assert items[str(one.id)] == {"mode": "selected", "shop_count": 1}
    assert items[str(two.id)] == {"mode": "selected", "shop_count": 2}
    assert items[str(everything.id)] == {"mode": "all", "shop_count": None}
    assert items[str(nothing.id)] == {"mode": "none", "shop_count": None}
    assert items[str(owner(db).id)] == {"mode": "company", "shop_count": None}


# --- Database-level consistency ------------------------------------------------------------------


def test_database_keeps_assignments_consistent(db: Session, make_user) -> None:
    a = add_shop(db, "A", "A-1")
    user = staff(db, make_user, [], mode="none")
    with pytest.raises(Exception, match="fk_user_shop_assignments_access"):  # not in selected mode
        db.execute(
            text("INSERT INTO user_shop_assignments (user_id, shop_id) VALUES (:u, :s)"),
            {"u": user.id, "s": a.id},
        )
        db.flush()
    db.rollback()
    with pytest.raises(Exception, match="needs at least one shop"):  # selected needs >= 1 shop
        db.execute(
            text("UPDATE user_shop_access SET access_mode = 'selected' WHERE user_id = :u"),
            {"u": user.id},
        )
        db.commit()
    db.rollback()
    with pytest.raises(Exception, match="Company Users only"):  # rows are for Company Users only
        db.execute(
            text("INSERT INTO user_shop_access (user_id, access_mode) VALUES (:u, 'all')"),
            {"u": owner_or_admin(db, make_user).id},
        )
        db.commit()
    db.rollback()
    with pytest.raises(Exception, match="ck_user_shop_access_mode"):
        db.execute(
            text("UPDATE user_shop_access SET access_mode = 'everything' WHERE user_id = :u"),
            {"u": user.id},
        )
        db.commit()
    db.rollback()
    selected = staff(db, make_user, [], mode="selected", shops=[a])
    with pytest.raises(Exception, match="user_shop_assignments_pkey"):  # no duplicates
        db.execute(
            text("INSERT INTO user_shop_assignments (user_id, shop_id) VALUES (:u, :s)"),
            {"u": selected.id, "s": a.id},
        )
        db.flush()
    db.rollback()
    with pytest.raises(
        Exception, match="user_shop_assignments_shop_id_fkey"
    ):  # shops cannot vanish
        db.execute(text("DELETE FROM shops WHERE id = :s"), {"s": a.id})
        db.flush()
    db.rollback()
