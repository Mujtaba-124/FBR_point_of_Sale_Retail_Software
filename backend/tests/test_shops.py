"""Shop Management: integrity, token security, permissions, isolation."""

import logging
import secrets
import threading
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.core import clock, secret_box
from app.core.config import get_settings
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
    User,
)
from app.services import shops as svc
from tests.conftest import csrf_header, login

URL = "/api/v1/company/shops"
ORIGIN = {"Origin": "http://localhost:3000"}
pytestmark = pytest.mark.usefixtures("valid_subscription")


def token() -> str:
    return "QA-TOKEN-" + secrets.token_hex(16)  # dummy, never a real FBR token


def h(client: TestClient) -> dict[str, str]:
    return {**csrf_header(client), **ORIGIN}


@pytest.fixture
def admin(client: TestClient, make_user) -> TestClient:
    email, password = make_user(AccessCategory.COMPANY_ADMIN, email="owner@example.test")
    assert login(client, email, password).status_code == 200
    return client


def staff(db: Session, make_user, permissions: list[str]) -> TestClient:
    """A signed-in Company User whose custom role has exactly these permissions."""
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
    client.role_id = role.id  # type: ignore[attr-defined]
    return client


def body(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "name": "Main Store",
        "branch_name": "Gulberg",
        "code": "LHR-01",
        "pos_id": "000123",
    }
    data.update(overrides)
    return data


def create(client: TestClient, **overrides: object):
    return client.post(URL, json=body(**overrides), headers=h(client))


def actions(db: Session) -> list[str]:
    db.expire_all()
    return list(
        db.scalars(
            select(AuditEvent.action)
            .where(AuditEvent.action.like("shop.%"))
            .order_by(AuditEvent.occurred_at)
        )
    )


# --- Creation and integrity -----------------------------------------------------


def test_create_shop_with_token_and_leading_zero_pos_id(admin: TestClient, db: Session) -> None:
    secret = token()
    res = create(admin, fbr_token=secret)
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["pos_id"] == "000123"  # string, leading zeros kept
    assert data["code"] == "LHR-01" and data["status"] == "active"
    assert data["fbr_token_status"] == "configured"
    assert secret not in res.text and "encrypted" not in res.text
    shop = db.scalar(select(Shop))
    assert shop.encrypted_fbr_token.startswith("v1:") and secret not in shop.encrypted_fbr_token
    assert secret_box.decrypt(shop.encrypted_fbr_token, svc.TOKEN_PURPOSE, secret_box.FBR) == secret
    with pytest.raises(secret_box.DecryptionError):  # SMTP keyring cannot open it
        secret_box.decrypt(shop.encrypted_fbr_token, svc.TOKEN_PURPOSE)
    assert actions(db) == ["shop.created", "shop.fbr_token_configured"]


def test_shop_without_token_is_explicitly_not_configured(admin: TestClient) -> None:
    data = create(admin).json()
    assert data["fbr_token_status"] == "not_configured" and data["fbr_token_updated_at"] is None


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"name": "   "}, "invalid_name"),
        ({"name": "Bad\nName"}, "invalid_name"),
        ({"branch_name": " \t "}, "invalid_branch_name"),
        ({"name": "x" * 121}, "invalid_name"),
        ({"code": "has space"}, "invalid_code"),
        ({"code": "-starts-with-dash"}, "invalid_code"),
        ({"code": "C" * 21}, "invalid_code"),
        ({"pos_id": "12 34"}, "invalid_pos_id"),
        ({"pos_id": "9" * 51}, "invalid_pos_id"),
        ({"fbr_token": "short"}, "invalid_fbr_token"),
        ({"fbr_token": "has a space inside"}, "invalid_fbr_token"),
    ],
)
def test_validation(admin: TestClient, db: Session, overrides: dict, code: str) -> None:
    res = create(admin, **overrides)
    assert res.status_code == 422 and res.json()["error"]["code"] == code
    assert db.scalar(select(func.count()).select_from(Shop)) == 0


def test_whitespace_is_normalized(admin: TestClient) -> None:
    data = create(
        admin, name="  Main   Store ", branch_name=" Gulberg  III ", code=" LHR-01 "
    ).json()
    assert (data["name"], data["branch_name"], data["code"]) == (
        "Main Store",
        "Gulberg III",
        "LHR-01",
    )


def test_code_and_pos_id_are_unique_case_insensitively(admin: TestClient) -> None:
    assert create(admin).status_code == 201
    res = create(admin, code="lhr-01", pos_id="999")
    assert res.status_code == 409 and res.json()["error"]["code"] == "shop_code_taken"
    res = create(admin, code="LHR-02", pos_id="000123")
    assert res.status_code == 409 and res.json()["error"]["code"] == "pos_id_taken"
    assert create(admin, code="LHR-02", pos_id="123").status_code == 201  # "123" != "000123"
    res = create(admin, code="LHR-03", pos_id="ABC")
    assert create(admin, code="LHR-04", pos_id="abc").json()["error"]["code"] == "pos_id_taken"
    assert res.status_code == 201


def test_database_enforces_uniqueness_under_concurrency(admin: TestClient, db: Session) -> None:
    actor = db.scalar(select(User).where(User.email == "owner@example.test"))
    factory = sessionmaker(bind=get_engine(), autoflush=False)
    barrier = threading.Barrier(6)
    outcomes: list[str] = []

    def worker(i: int) -> None:
        with factory() as session:
            barrier.wait()
            try:
                svc.create_shop(
                    session,
                    actor=session.get(User, actor.id),
                    name=f"Race {i}",
                    branch_name="B",
                    code="RACE" if i % 2 else "race",
                    pos_id=f"P{i}",
                    fbr_token=None,
                )
                outcomes.append("created")
            except AppError as exc:
                outcomes.append(exc.code)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count("created") == 1 and outcomes.count("shop_code_taken") == 5
    assert db.scalar(select(func.count()).select_from(Shop)) == 1


def test_raw_duplicate_insert_is_refused_by_the_index(db: Session) -> None:
    db.add(Shop(name="A", branch_name="B", code="Dup", pos_id="1"))
    db.commit()
    with pytest.raises(Exception, match="uq_shops_code_lower"):
        db.execute(
            text("INSERT INTO shops (name, branch_name, code, pos_id) VALUES ('X','Y','DUP','2')")
        )
    db.rollback()


# --- Editing, token replacement, stale forms ----------------------------------------


def test_edit_profile_with_version_and_stale_forms(admin: TestClient, db: Session) -> None:
    shop = create(admin, fbr_token=token()).json()
    before = db.scalar(select(Shop.encrypted_fbr_token))
    res = admin.patch(
        f"{URL}/{shop['id']}",
        json={"expected_version": 1, "name": "Flagship", "pos_id": "0042"},
        headers=h(admin),
    )
    assert res.status_code == 200 and res.json()["version"] == 2
    assert res.json()["pos_id"] == "0042"
    assert db.scalar(select(Shop.encrypted_fbr_token)) == before  # edit never touches the token
    stale = admin.patch(
        f"{URL}/{shop['id']}", json={"expected_version": 1, "name": "Old tab"}, headers=h(admin)
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_shop"
    audit = db.scalars(select(AuditEvent.details).where(AuditEvent.action == "shop.updated")).all()
    assert audit[-1]["changed"] == ["name", "pos_id"]


def test_edit_cannot_take_another_shops_code(admin: TestClient) -> None:
    create(admin)
    other = create(admin, code="KHI-01", pos_id="777").json()
    res = admin.patch(
        f"{URL}/{other['id']}", json={"expected_version": 1, "code": "lhr-01"}, headers=h(admin)
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "shop_code_taken"


def test_token_configure_then_replace(admin: TestClient, db: Session) -> None:
    shop = create(admin).json()
    first, second = token(), token()
    res = admin.put(
        f"{URL}/{shop['id']}/fbr-token",
        json={"expected_version": 1, "fbr_token": first},
        headers=h(admin),
    )
    assert res.status_code == 200 and res.json()["fbr_token_status"] == "configured"
    stale = admin.put(
        f"{URL}/{shop['id']}/fbr-token",
        json={"expected_version": 1, "fbr_token": second},
        headers=h(admin),
    )
    assert stale.status_code == 409
    res = admin.put(
        f"{URL}/{shop['id']}/fbr-token",
        json={"expected_version": 2, "fbr_token": second},
        headers=h(admin),
    )
    assert res.status_code == 200 and first not in res.text and second not in res.text
    db.expire_all()
    stored = db.scalar(select(Shop.encrypted_fbr_token))
    assert secret_box.decrypt(stored, svc.TOKEN_PURPOSE, secret_box.FBR) == second
    assert actions(db)[-2:] == ["shop.fbr_token_configured", "shop.fbr_token_replaced"]


def test_blank_token_never_clears(admin: TestClient, db: Session) -> None:
    shop = create(admin, fbr_token=token()).json()
    res = admin.put(
        f"{URL}/{shop['id']}/fbr-token",
        json={"expected_version": 1, "fbr_token": "   "},
        headers=h(admin),
    )
    assert res.status_code == 422
    res = admin.put(
        f"{URL}/{shop['id']}/fbr-token",
        json={"expected_version": 1, "fbr_token": ""},
        headers=h(admin),
    )
    assert res.status_code == 422
    assert db.scalar(select(Shop.encrypted_fbr_token)) is not None


def test_missing_fbr_key_fails_securely(admin: TestClient, db: Session, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "fbr_token_encryption_key", None)
    res = create(admin, fbr_token=token())
    assert res.status_code == 503 and res.json()["error"]["code"] == "fbr_key_missing"
    assert db.scalar(select(func.count()).select_from(Shop)) == 0


def test_fbr_key_must_differ_from_smtp_key(monkeypatch) -> None:
    monkeypatch.setattr(
        get_settings(), "fbr_token_encryption_key", get_settings().email_settings_encryption_key
    )
    with pytest.raises(secret_box.EncryptionKeyError, match="must be different"):
        secret_box.encrypt("x" * 10, svc.TOKEN_PURPOSE, secret_box.FBR)


def test_rotated_key_reports_unreadable_until_resaved(admin: TestClient, monkeypatch) -> None:
    import base64

    shop = create(admin, fbr_token=token()).json()
    monkeypatch.setattr(
        get_settings(),
        "fbr_token_encryption_key",
        base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    )
    assert admin.get(f"{URL}/{shop['id']}").json()["fbr_token_status"] == "unreadable"


# --- Active / inactive ------------------------------------------------------------------


def test_deactivate_and_reactivate_keep_identity_and_token(admin: TestClient, db: Session) -> None:
    shop = create(admin, fbr_token=token()).json()
    before = db.scalar(select(Shop.encrypted_fbr_token))
    res = admin.post(
        f"{URL}/{shop['id']}/deactivate", json={"expected_version": 1}, headers=h(admin)
    )
    assert res.status_code == 200 and res.json()["status"] == "inactive"
    assert res.json()["id"] == shop["id"] and res.json()["fbr_token_status"] == "configured"
    res = admin.post(
        f"{URL}/{shop['id']}/reactivate", json={"expected_version": 2}, headers=h(admin)
    )
    assert res.status_code == 200 and res.json()["status"] == "active"
    db.expire_all()
    assert db.scalar(select(Shop.encrypted_fbr_token)) == before
    assert db.scalar(select(func.count()).select_from(Shop)) == 1  # never deleted
    assert actions(db)[-2:] == ["shop.deactivated", "shop.reactivated"]


def test_inactive_shop_still_blocks_its_code(admin: TestClient) -> None:
    shop = create(admin).json()
    admin.post(f"{URL}/{shop['id']}/deactivate", json={"expected_version": 1}, headers=h(admin))
    assert create(admin, pos_id="555").json()["error"]["code"] == "shop_code_taken"


# --- Listing ------------------------------------------------------------------------------


def test_search_filter_sort_pagination_and_summary(admin: TestClient) -> None:
    for i in range(12):
        create(
            admin,
            name=f"Shop {i:02d}",
            code=f"C{i:02d}",
            pos_id=f"{i:04d}",
            branch_name="North" if i % 2 else "South",
        )
    first = admin.get(f"{URL}?search=C0").json()["items"][0]
    admin.post(f"{URL}/{first['id']}/deactivate", json={"expected_version": 1}, headers=h(admin))
    page = admin.get(f"{URL}?limit=5&offset=0&sort=code&order=desc").json()
    assert page["total"] == 12 and len(page["items"]) == 5
    assert [s["code"] for s in page["items"]] == ["C11", "C10", "C09", "C08", "C07"]
    assert page["summary"] == {"total": 12, "active": 11, "inactive": 1}
    assert admin.get(f"{URL}?status=inactive").json()["total"] == 1
    assert admin.get(f"{URL}?search=north").json()["total"] == 6
    assert admin.get(f"{URL}?search=0007").json()["total"] == 1  # POS ID
    assert admin.get(f"{URL}?search=%25").json()["total"] == 0
    assert admin.get(f"{URL}?sort=fbr_token").status_code == 422


def test_unknown_shop_is_404(admin: TestClient) -> None:
    import uuid

    assert admin.get(f"{URL}/{uuid.uuid4()}").status_code == 404
    assert admin.get(f"{URL}/not-a-uuid").status_code == 422


# --- Permissions ---------------------------------------------------------------------------


def test_unauthenticated_and_super_admin_denied(client: TestClient, make_user) -> None:
    assert client.get(URL).status_code == 401
    email, password = make_user(AccessCategory.SUPER_ADMIN)
    assert login(client, email, password).status_code == 200
    assert client.get(URL).status_code == 403
    assert client.post(URL, json=body(), headers=h(client)).status_code == 403


def test_company_user_without_shop_rights_is_denied(
    admin: TestClient, db: Session, make_user
) -> None:
    shop = create(admin).json()
    user = staff(db, make_user, [])
    for res in (
        user.get(URL),
        user.get(f"{URL}/{shop['id']}"),
        user.post(URL, json=body(code="X1", pos_id="9"), headers=h(user)),
        user.patch(
            f"{URL}/{shop['id']}", json={"expected_version": 1, "name": "X"}, headers=h(user)
        ),
        user.post(f"{URL}/{shop['id']}/deactivate", json={"expected_version": 1}, headers=h(user)),
        user.put(
            f"{URL}/{shop['id']}/fbr-token",
            json={"expected_version": 1, "fbr_token": token()},
            headers=h(user),
        ),
    ):
        assert res.status_code == 403, res.request.url
    assert user.get("/api/v1/company/workspace").json()["permissions"] == ["dashboard.view"]


def test_each_capability_is_enforced_separately(admin: TestClient, db: Session, make_user) -> None:
    shop = create(admin).json()
    viewer = staff(db, make_user, ["shops.view"])
    assert viewer.get(URL).status_code == 200
    assert viewer.get(f"{URL}/{shop['id']}").status_code == 200
    assert viewer.post(URL, json=body(code="V1", pos_id="V1"), headers=h(viewer)).status_code == 403
    assert (
        viewer.patch(
            f"{URL}/{shop['id']}", json={"expected_version": 1, "name": "V"}, headers=h(viewer)
        ).status_code
        == 403
    )
    assert (
        viewer.post(
            f"{URL}/{shop['id']}/deactivate", json={"expected_version": 1}, headers=h(viewer)
        ).status_code
        == 403
    )

    editor = staff(db, make_user, ["shops.view", "shops.create", "shops.edit"])
    # Basic Create/Edit never implies token management.
    res = editor.post(URL, json=body(code="E1", pos_id="E1", fbr_token=token()), headers=h(editor))
    assert res.status_code == 403
    assert editor.post(URL, json=body(code="E1", pos_id="E1"), headers=h(editor)).status_code == 201
    assert (
        editor.patch(
            f"{URL}/{shop['id']}", json={"expected_version": 1, "name": "Edited"}, headers=h(editor)
        ).status_code
        == 200
    )
    res = editor.put(
        f"{URL}/{shop['id']}/fbr-token",
        json={"expected_version": 2, "fbr_token": token()},
        headers=h(editor),
    )
    assert res.status_code == 403
    assert actions(db).count("shop.fbr_token_denied") == 2
    assert (
        editor.post(
            f"{URL}/{shop['id']}/deactivate", json={"expected_version": 2}, headers=h(editor)
        ).status_code
        == 403
    )

    integrator = staff(db, make_user, ["shops.view", "shops.manage_integration"])
    res = integrator.put(
        f"{URL}/{shop['id']}/fbr-token",
        json={"expected_version": 2, "fbr_token": token()},
        headers=h(integrator),
    )
    assert res.status_code == 200

    operator = staff(db, make_user, ["shops.view", "shops.delete"])
    res = operator.post(
        f"{URL}/{shop['id']}/deactivate", json={"expected_version": 3}, headers=h(operator)
    )
    assert res.status_code == 200 and res.json()["status"] == "inactive"


def test_role_change_applies_to_an_active_session(
    admin: TestClient, db: Session, make_user
) -> None:
    user = staff(db, make_user, ["shops.view"])
    assert user.get(URL).status_code == 200
    db.execute(
        text(
            "DELETE FROM company_role_permissions WHERE role_id = :r AND permission = 'shops.view'"
        ),
        {"r": user.role_id},
    )  # type: ignore[attr-defined]
    db.commit()
    assert user.get(URL).status_code == 403  # same session, no re-login


def test_csrf_and_foreign_origin(admin: TestClient) -> None:
    res = admin.post(URL, json=body(), headers=ORIGIN)
    assert res.status_code == 403 and res.json()["error"]["code"] == "csrf_failed"
    res = admin.post(
        URL, json=body(), headers={**csrf_header(admin), "Origin": "https://evil.example"}
    )
    assert res.status_code == 403


def test_expired_subscription_blocks_shops(admin: TestClient, db: Session) -> None:
    today = clock.utcnow().date()
    db.execute(
        update(AppSubscription).values(
            start_date=today - timedelta(days=400), expiry_date=today - timedelta(days=1)
        )
    )
    db.commit()
    res = admin.get(URL)
    assert res.status_code == 403 and res.json()["error"]["code"] == "subscription_expired"


# --- Secrets never leak ------------------------------------------------------------------


def test_token_never_in_responses_logs_or_audit(
    admin: TestClient, db: Session, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    secret = token()
    shop = create(admin, fbr_token=secret).json()
    replacement = token()
    admin.put(
        f"{URL}/{shop['id']}/fbr-token",
        json={"expected_version": 1, "fbr_token": replacement},
        headers=h(admin),
    )
    responses = admin.get(URL).text + admin.get(f"{URL}/{shop['id']}").text
    ciphertext = db.scalar(select(Shop.encrypted_fbr_token))
    audit_dump = " ".join(str(d) for d in db.scalars(select(AuditEvent.details)))
    key = get_settings().fbr_token_encryption_key or ""
    for needle in (secret, replacement, ciphertext, key):
        assert needle not in responses
        assert needle not in caplog.text
        assert needle not in audit_dump


# --- Dashboard ---------------------------------------------------------------------------


def test_dashboard_total_shops_is_real(admin: TestClient) -> None:
    summary = "/api/v1/company/dashboard/summary"
    assert admin.get(summary).json()["metrics"]["total_shops"]["value"] == 0
    shop = create(admin).json()
    create(admin, code="B2", pos_id="B2")
    admin.post(f"{URL}/{shop['id']}/deactivate", json={"expected_version": 1}, headers=h(admin))
    metrics = admin.get(summary).json()["metrics"]
    assert metrics["total_shops"] == {"available": True, "value": 2, "unavailable_reason": None}
    assert metrics["active_shops"]["value"] == 1
    assert metrics["pending_approvals"]["available"] is False


def test_navigation_permission_for_shops(admin: TestClient, db: Session, make_user) -> None:
    viewer = staff(db, make_user, ["shops.view"])
    assert "shops.view" in viewer.get("/api/v1/company/workspace").json()["permissions"]
    catalog = admin.get("/api/v1/company/permissions").json()["modules"]
    shops_module = next(m for m in catalog if m["key"] == "shops")
    assert shops_module["available"] is True
    labels = {c["key"]: c["label"] for c in shops_module["capabilities"]}
    assert labels["shops.delete"] == "Deactivate / Reactivate"
