"""Company Workspace shop context: options contract, validation, authorization."""

import secrets
import threading
import time
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core import clock
from app.core.errors import AppError
from app.db.session import get_engine
from app.main import app
from app.models import (
    AccessCategory,
    AppSubscription,
    CompanyRole,
    CompanyRolePermission,
    Shop,
    User,
)
from app.services import shop_context as svc
from app.services import shops as shop_svc
from tests.conftest import csrf_header, login

OPTIONS = "/api/v1/company/shop-options"
DASHBOARD = "/api/v1/company/dashboard/summary"
WORKSPACE = "/api/v1/company/workspace"
ORIGIN = {"Origin": "http://localhost:3000"}
pytestmark = pytest.mark.usefixtures("valid_subscription")


def signed_in(make_user, category: AccessCategory, email: str | None = None) -> TestClient:
    address, password = make_user(category, email=email)
    client = TestClient(app, base_url="https://testserver")
    assert login(client, address, password).status_code == 200
    return client


@pytest.fixture
def admin(make_user) -> TestClient:
    return signed_in(make_user, AccessCategory.COMPANY_ADMIN, "owner@example.test")


def staff(db: Session, make_user, permissions: list[str]) -> tuple[TestClient, uuid.UUID]:
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
    return client, role.id


def add_shop(
    db: Session, name: str, code: str, *, active: bool = True, token: str | None = None
) -> Shop:
    shop = Shop(
        name=name,
        branch_name="Hidden Branch",
        code=code,
        pos_id=f"POS{code}",
        is_active=active,
        encrypted_fbr_token=token,
        fbr_token_updated_at=clock.utcnow() if token else None,
    )
    db.add(shop)
    db.commit()
    return shop


def owner(db: Session) -> User:
    return db.scalar(select(User).where(User.email == "owner@example.test"))  # type: ignore[return-value]


# --- Options contract -------------------------------------------------------------------


def test_options_list_active_shops_only_with_id_name_and_code(
    admin: TestClient, db: Session
) -> None:
    b = add_shop(db, "Cheena Main Shop", "CH-002")
    a = add_shop(db, "Cheena Main Shop", "CH-001")  # duplicate name: code tells them apart
    add_shop(db, "Old Closed Shop", "OLD-1", active=False)
    res = admin.get(OPTIONS)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2 and data["truncated"] is False
    assert data["items"] == [
        {"id": str(a.id), "name": "Cheena Main Shop", "code": "CH-001"},
        {"id": str(b.id), "name": "Cheena Main Shop", "code": "CH-002"},
    ]
    assert data["selection"] == {"status": "all", "shop": None}
    assert set(data["items"][0]) == {"id", "name", "code"}


def test_options_never_carry_tokens_pos_ids_or_branches(admin: TestClient, db: Session) -> None:
    ciphertext = "v1:test:" + secrets.token_hex(24)
    shop = add_shop(db, "Secret Holder", "SEC-1", token=ciphertext)
    body = admin.get(OPTIONS, params={"selected": str(shop.id)}).text
    for needle in (
        ciphertext,
        "POSSEC-1",
        "Hidden Branch",
        "fbr",
        "token",
        "pos_id",
        "branch",
        "is_active",
    ):
        assert needle not in body, needle


def test_empty_active_list_is_honest(admin: TestClient, db: Session) -> None:
    add_shop(db, "Closed", "CL-1", active=False)
    data = admin.get(OPTIONS).json()
    assert data["items"] == [] and data["total"] == 0


def test_large_list_is_one_sorted_response(admin: TestClient, db: Session) -> None:
    for i in range(60):
        db.add(Shop(name=f"Shop {i:02d}", branch_name="B", code=f"S{i:02d}", pos_id=f"P{i:02d}"))
    db.commit()
    items = admin.get(OPTIONS).json()["items"]
    assert len(items) == 60
    assert [i["code"] for i in items] == sorted(i["code"] for i in items)


def test_rename_keeps_the_id_and_shows_the_new_name(admin: TestClient, db: Session) -> None:
    shop = add_shop(db, "Before", "RN-1")
    shop_svc.update_shop(
        db,
        actor=owner(db),
        shop_id=shop.id,
        expected_version=1,
        name="After Rename",
        branch_name=None,
        code=None,
        pos_id=None,
    )
    data = admin.get(OPTIONS, params={"selected": str(shop.id)}).json()
    assert data["selection"]["status"] == "active"
    assert data["selection"]["shop"] == {"id": str(shop.id), "name": "After Rename", "code": "RN-1"}
    dash = admin.get(DASHBOARD, params={"shop_id": str(shop.id)}).json()["context"]
    assert dash == {
        "scope": "shop",
        "shop": {"id": str(shop.id), "name": "After Rename", "code": "RN-1"},
    }


# --- Validation ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "status"),
    [
        ("not-a-uuid", "invalid"),
        ("1; DROP TABLE shops", "invalid"),
        (str(uuid.uuid4()), "not_found"),
        ("all", "all"),
        ("", "all"),
    ],
)
def test_selection_verdicts(admin: TestClient, raw: str, status: str) -> None:
    data = admin.get(OPTIONS, params={"selected": raw}).json()
    assert data["selection"] == {"status": status, "shop": None}


def test_dashboard_rejects_invalid_unknown_and_inactive_shops(
    admin: TestClient, db: Session
) -> None:
    closed = add_shop(db, "Closed", "CL-1", active=False)
    cases = {
        "nope": (422, "invalid_shop_id"),
        str(uuid.uuid4()): (404, "shop_not_found"),
        str(closed.id): (409, "shop_inactive"),
    }
    for raw, (code, error) in cases.items():
        res = admin.get(DASHBOARD, params={"shop_id": raw})
        assert res.status_code == code and res.json()["error"]["code"] == error, raw
    assert (
        admin.get(OPTIONS, params={"selected": str(closed.id)}).json()["selection"]["status"]
        == "inactive"
    )


def test_deactivation_while_selected_invalidates_the_selection(
    admin: TestClient, db: Session
) -> None:
    shop = add_shop(db, "Soon Closed", "SC-1")
    assert admin.get(DASHBOARD, params={"shop_id": str(shop.id)}).status_code == 200
    shop_svc.set_active(db, actor=owner(db), shop_id=shop.id, expected_version=1, active=False)
    assert (
        admin.get(DASHBOARD, params={"shop_id": str(shop.id)}).json()["error"]["code"]
        == "shop_inactive"
    )
    data = admin.get(OPTIONS, params={"selected": str(shop.id)}).json()
    assert data["selection"] == {"status": "inactive", "shop": None}  # never another shop
    assert str(shop.id) not in [i["id"] for i in data["items"]]


# --- Dashboard ---------------------------------------------------------------------------------


def test_dashboard_keeps_company_wide_counts_labelled(admin: TestClient, db: Session) -> None:
    one = add_shop(db, "One", "ONE")
    add_shop(db, "Two", "TWO")
    everything = admin.get(DASHBOARD).json()
    scoped = admin.get(DASHBOARD, params={"shop_id": str(one.id)}).json()
    assert everything["context"] == {"scope": "all", "shop": None}
    assert scoped["context"]["scope"] == "shop" and scoped["context"]["shop"]["code"] == "ONE"
    assert scoped["metrics"] == everything["metrics"]  # nothing invented for one shop
    assert scoped["metrics"]["total_shops"]["value"] == 2
    assert scoped["metric_scopes"]["total_shops"] == "company"
    assert scoped["metric_scopes"]["active_users"] == "company"
    assert scoped["metric_scopes"]["pending_approvals"] == "context"
    assert scoped["metrics"]["pending_approvals"]["available"] is False


# --- Authorization ------------------------------------------------------------------------------


def test_unauthenticated_is_rejected(client: TestClient) -> None:
    assert client.get(OPTIONS).status_code == 401
    assert client.get(DASHBOARD, params={"shop_id": str(uuid.uuid4())}).status_code == 401


def test_super_admin_has_no_company_shop_context(make_user, db: Session) -> None:
    add_shop(db, "Main", "M-1")
    root = signed_in(make_user, AccessCategory.SUPER_ADMIN)
    assert root.get(OPTIONS).status_code == 403
    assert root.get(DASHBOARD).status_code == 403


def test_company_admin_workspace_enables_the_selector(admin: TestClient) -> None:
    assert admin.get(WORKSPACE).json()["shop_context_enabled"] is True


def test_company_user_cannot_gain_anything_through_a_selection(db: Session, make_user) -> None:
    shop = add_shop(db, "Main", "M-1")
    every_assignable = [
        "shops.view",
        "shops.create",
        "shops.edit",
        "shops.delete",
        "shops.manage_integration",
        "uploads.view",
        "approvals.view",
        "fbr_sync.view",
        "reports.view",
    ]
    user, _ = staff(db, make_user, every_assignable)
    assert (
        user.get(WORKSPACE).json()["shop_context_enabled"] is False
    )  # no implemented consumer yet
    assert user.get(OPTIONS).status_code == 403
    for params in ({}, {"shop_id": str(shop.id)}):
        assert user.get(DASHBOARD, params=params).status_code == 403
    # Selecting a shop does not unlock admin-only areas either.
    assert user.get("/api/v1/company/users", params={"shop_id": str(shop.id)}).status_code == 403
    # Existing Shop Management access is unchanged and still company-wide.
    assert user.get("/api/v1/company/shops", params={"shop_id": str(shop.id)}).status_code == 200


def test_role_changes_apply_without_signing_in_again(db: Session, make_user, monkeypatch) -> None:
    """With a (future) implemented consumer, the selector follows the role live."""
    monkeypatch.setattr(
        svc, "CONSUMERS", (svc.Consumer("uploads", implemented=True, permission="uploads.view"),)
    )
    add_shop(db, "Main", "M-1")
    user, role_id = staff(db, make_user, ["uploads.view"])
    assert user.get(OPTIONS).status_code == 200
    db.execute(
        CompanyRolePermission.__table__.delete().where(
            CompanyRolePermission.role_id == role_id,
            CompanyRolePermission.permission == "uploads.view",
        )
    )
    db.commit()
    assert user.get(OPTIONS).status_code == 403
    assert user.get(WORKSPACE).json()["shop_context_enabled"] is False


def test_deactivated_account_loses_access(admin: TestClient, db: Session) -> None:
    assert admin.get(OPTIONS).status_code == 200
    db.execute(update(User).where(User.email == "owner@example.test").values(is_active=False))
    db.commit()
    assert admin.get(OPTIONS).status_code in (401, 403)


def test_expired_subscription_blocks_the_selector(admin: TestClient, db: Session) -> None:
    today = clock.utcnow().date()
    db.execute(
        update(AppSubscription).values(
            start_date=today - timedelta(days=400), expiry_date=today - timedelta(days=1)
        )
    )
    db.commit()
    res = admin.get(OPTIONS)
    assert res.status_code == 403 and res.json()["error"]["code"] == "subscription_expired"


def test_no_selection_state_is_kept_between_users_or_sessions(
    admin: TestClient, db: Session, make_user
) -> None:
    shop = add_shop(db, "Main", "M-1")
    assert (
        admin.get(DASHBOARD, params={"shop_id": str(shop.id)}).json()["context"]["scope"] == "shop"
    )
    second_admin = signed_in(make_user, AccessCategory.COMPANY_ADMIN)
    assert second_admin.get(DASHBOARD).json()["context"] == {"scope": "all", "shop": None}
    assert second_admin.get(OPTIONS).json()["selection"]["status"] == "all"
    assert admin.get(DASHBOARD).json()["context"]["scope"] == "all"  # stateless per request


def test_options_is_read_only(admin: TestClient) -> None:
    for method in ("post", "put", "patch", "delete"):
        res = getattr(admin, method)(OPTIONS, headers={**csrf_header(admin), **ORIGIN})
        assert res.status_code == 405


# --- Future-module contract ----------------------------------------------------------------------


def test_resolver_modes_for_future_modules(admin: TestClient, db: Session) -> None:
    active = add_shop(db, "Open", "OP-1")
    closed = add_shop(db, "Closed", "CL-1", active=False)
    user = owner(db)
    assert svc.resolve(db, user, None).scope == "all"
    with pytest.raises(AppError) as exc:
        svc.resolve(db, user, None, purpose=svc.Purpose.OPERATE, require_single_shop=True)
    assert exc.value.code == "shop_required"  # e.g. Excel Upload never runs for All Shops
    assert svc.resolve(db, user, str(active.id), purpose=svc.Purpose.OPERATE).shop_id == active.id
    db.rollback()
    for purpose in (svc.Purpose.READ, svc.Purpose.OPERATE):
        with pytest.raises(AppError) as exc:
            svc.resolve(db, user, str(closed.id), purpose=purpose)
        assert exc.value.code == "shop_inactive"
        db.rollback()
    historical = svc.resolve(db, user, str(closed.id), purpose=svc.Purpose.HISTORY)
    assert historical.shop_id == closed.id and historical.is_active is False


def test_resolver_denies_accounts_without_a_shop_context(db: Session, make_user) -> None:
    email, _ = make_user(AccessCategory.SUPER_ADMIN)
    root = db.scalar(select(User).where(User.email == email))
    with pytest.raises(AppError) as exc:
        svc.resolve(db, root, None)  # type: ignore[arg-type]
    assert exc.value.status_code == 403


def test_operational_resolution_holds_off_a_concurrent_deactivation(
    admin: TestClient, db: Session
) -> None:
    shop = add_shop(db, "Busy", "BZ-1")
    actor_id = owner(db).id
    factory = sessionmaker(bind=get_engine(), autoflush=False)
    writer = factory()
    svc.resolve(writer, writer.get(User, actor_id), str(shop.id), purpose=svc.Purpose.OPERATE)  # type: ignore[arg-type]
    done: list[bool] = []

    def deactivate() -> None:
        with factory() as session:
            shop_svc.set_active(
                session,
                actor=session.get(User, actor_id),
                shop_id=shop.id,
                expected_version=1,
                active=False,
            )  # type: ignore[arg-type]
            done.append(True)

    thread = threading.Thread(target=deactivate)
    thread.start()
    time.sleep(0.5)
    assert thread.is_alive() and not done  # waits for the operational write to finish
    writer.commit()
    writer.close()
    thread.join(timeout=10)
    assert done == [True]
