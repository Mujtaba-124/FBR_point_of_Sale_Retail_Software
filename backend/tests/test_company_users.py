"""Company User Management + Roles & Permissions: capacity, protection, authorization."""

import threading
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core import clock
from app.core.errors import AppError
from app.core.security import hash_password, hash_token
from app.db.session import get_engine
from app.main import app
from app.models import (
    AccessCategory,
    AppSubscription,
    AuditEvent,
    AuthenticationSession,
    CompanyRole,
    PasswordSetupToken,
    User,
)
from app.services import company_users as users_svc
from app.services.permissions import ALL_KEYS, has_permission
from tests.conftest import csrf_header, login, random_password

ORIGIN = {"Origin": "http://localhost:3000"}
USERS = "/api/v1/company/users"
ROLES = "/api/v1/company/roles"
pytestmark = pytest.mark.usefixtures("valid_subscription")


def headers(client: TestClient) -> dict[str, str]:
    return {**csrf_header(client), **ORIGIN}


@pytest.fixture
def admin(client: TestClient, make_user) -> TestClient:
    email, password = make_user(AccessCategory.COMPANY_ADMIN, email="owner@example.test")
    assert login(client, email, password).status_code == 200
    return client


def system_role(db: Session, key: str) -> CompanyRole:
    role = db.scalar(select(CompanyRole).where(CompanyRole.system_key == key))
    assert role is not None
    return role


def add_company_users(db: Session, count: int, *, active: bool = True, prefix: str = "u") -> None:
    role = system_role(db, "company_user")
    for i in range(count):
        db.add(
            User(
                email=f"{prefix}{i}-{uuid.uuid4().hex[:6]}@example.test",
                full_name=f"User {prefix}{i}",
                password_hash="x",
                access_category=AccessCategory.COMPANY_USER,
                company_role_id=role.id,
                is_active=active,
            )
        )
    db.commit()


def create(client: TestClient, db: Session, email: str, role_id: uuid.UUID | None = None):
    role_id = role_id or system_role(db, "company_user").id
    return client.post(
        USERS,
        json={"full_name": "New Person", "email": email, "role_id": str(role_id)},
        headers=headers(client),
    )


def capacity(client: TestClient) -> dict:
    return client.get(USERS).json()["capacity"]


def actions(db: Session, prefix: str) -> list[str]:
    db.expire_all()
    return list(
        db.scalars(
            select(AuditEvent.action)
            .where(AuditEvent.action.startswith(prefix))
            .order_by(AuditEvent.occurred_at)
        )
    )


# --- 15-account capacity --------------------------------------------------------


def test_admin_counts_as_one_and_super_admin_is_excluded(admin: TestClient, make_user) -> None:
    make_user(AccessCategory.SUPER_ADMIN)
    assert capacity(admin) == {"active": 1, "limit": 15, "available": 14, "inactive": 0}


def test_fourteen_users_fill_the_limit_and_the_sixteenth_is_refused(
    admin: TestClient, db: Session
) -> None:
    add_company_users(db, 13)
    assert create(admin, db, "fourteenth@example.test").status_code == 201
    assert capacity(admin) == {"active": 15, "limit": 15, "available": 0, "inactive": 0}
    res = create(admin, db, "sixteenth@example.test")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "user_limit_reached"
    assert (
        db.scalar(
            select(func.count()).select_from(User).where(User.email == "sixteenth@example.test")
        )
        == 0
    )
    assert "company_user.limit_reached" in actions(db, "company_user.")


def test_inactive_users_do_not_count_and_slots_move(admin: TestClient, db: Session) -> None:
    add_company_users(db, 14)
    add_company_users(db, 3, active=False, prefix="old")
    assert capacity(admin) == {"active": 15, "limit": 15, "available": 0, "inactive": 3}
    target = db.scalar(select(User).where(User.email.like("u0-%")))
    inactive = db.scalar(select(User).where(User.email.like("old0-%")))
    # Full: reactivation refused.
    res = admin.post(f"{USERS}/{inactive.id}/reactivate", headers=headers(admin))
    assert res.status_code == 409 and res.json()["error"]["code"] == "user_limit_reached"
    # Deactivation frees a slot ...
    res = admin.post(f"{USERS}/{target.id}/deactivate", headers=headers(admin))
    assert res.status_code == 200 and res.json()["capacity"]["active"] == 14
    # ... which reactivation consumes.
    res = admin.post(f"{USERS}/{inactive.id}/reactivate", headers=headers(admin))
    assert res.status_code == 200
    assert res.json()["capacity"] == {"active": 15, "limit": 15, "available": 0, "inactive": 3}


def test_concurrent_creates_cannot_exceed_the_limit(admin: TestClient, db: Session) -> None:
    add_company_users(db, 13)  # 14/15 active: one slot left
    actor = db.scalar(select(User).where(User.email == "owner@example.test"))
    role_id = system_role(db, "company_user").id
    factory = sessionmaker(bind=get_engine(), autoflush=False)
    results: list[str] = []
    barrier = threading.Barrier(5)

    def worker(i: int) -> None:
        with factory() as session:
            barrier.wait()
            try:
                users_svc.create_user(
                    session,
                    actor=session.get(User, actor.id),
                    full_name=f"Racer {i}",
                    email=f"racer{i}@example.test",
                    role_id=role_id,
                )
                results.append("created")
            except AppError as exc:
                results.append(exc.code)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["created"] + ["user_limit_reached"] * 4
    assert users_svc.capacity(db).active == 15


def test_database_trigger_blocks_a_sixteenth_account_on_any_write_path(db: Session) -> None:
    add_company_users(db, 15)  # 15/15 written directly
    with pytest.raises(IntegrityError, match="company_user_limit_reached"):
        add_company_users(db, 1, prefix="bypass")
    db.rollback()


def test_trigger_serializes_parallel_raw_inserts(db: Session) -> None:
    add_company_users(db, 14)
    engine = get_engine()
    role_id = system_role(db, "company_user").id
    insert = text(
        "INSERT INTO users (email, full_name, password_hash, access_category, company_role_id)"
        " VALUES (:e, 'Raw', 'x', 'company_user', :r)"
    )
    first = engine.connect()
    tx = first.begin()
    first.execute(insert, {"e": "raw1@example.test", "r": role_id})  # holds the advisory lock
    outcome: list[str] = []

    def second() -> None:
        with engine.connect() as conn:
            try:
                with conn.begin():
                    conn.execute(insert, {"e": "raw2@example.test", "r": role_id})
                outcome.append("inserted")
            except IntegrityError:
                outcome.append("refused")

    t = threading.Thread(target=second)
    t.start()
    t.join(timeout=1)
    assert t.is_alive()  # waiting for the first transaction's lock
    tx.commit()
    first.close()
    t.join(timeout=10)
    assert outcome == ["refused"]
    assert users_svc.capacity(db).active == 15


def test_duplicate_submission_creates_one_account(admin: TestClient, db: Session) -> None:
    assert create(admin, db, "twice@example.test").status_code == 201
    res = create(admin, db, "TWICE@example.test")
    assert res.status_code == 409 and res.json()["error"]["code"] == "email_already_exists"
    assert (
        db.scalar(
            select(func.count())
            .select_from(User)
            .where(func.lower(User.email) == "twice@example.test")
        )
        == 1
    )


def test_email_of_inactive_user_points_to_reactivation(admin: TestClient, db: Session) -> None:
    add_company_users(db, 1, active=False, prefix="gone")
    email = db.scalar(select(User.email).where(User.email.like("gone0-%")))
    res = create(admin, db, email)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "email_belongs_to_inactive_user"


def test_super_admin_email_cannot_be_reused(admin: TestClient, db: Session, make_user) -> None:
    email, _ = make_user(AccessCategory.SUPER_ADMIN)
    assert create(admin, db, email).json()["error"]["code"] == "email_already_exists"


# --- Protected Company Admin -------------------------------------------------------


def test_company_admin_is_protected(admin: TestClient, db: Session) -> None:
    owner = db.scalar(select(User).where(User.email == "owner@example.test"))
    listed = {u["email"]: u for u in admin.get(USERS).json()["items"]}
    assert listed["owner@example.test"]["is_protected"] is True
    assert listed["owner@example.test"]["role"]["name"] == "Company Admin"
    res = admin.post(f"{USERS}/{owner.id}/deactivate", headers=headers(admin))
    assert res.status_code == 403 and res.json()["error"]["code"] == "protected_admin"
    custom = admin.post(
        ROLES, json={"name": "Clerk", "permissions": []}, headers=headers(admin)
    ).json()
    res = admin.patch(f"{USERS}/{owner.id}", json={"role_id": custom["id"]}, headers=headers(admin))
    assert res.status_code == 403
    # The name is an ordinary profile field.
    res = admin.patch(
        f"{USERS}/{owner.id}", json={"full_name": "Owner Name"}, headers=headers(admin)
    )
    assert res.status_code == 200 and res.json()["full_name"] == "Owner Name"
    db.expire_all()
    assert db.get(User, owner.id).is_active is True


def test_new_accounts_are_never_company_admins(admin: TestClient, db: Session) -> None:
    admin_role = system_role(db, "company_admin")
    res = create(admin, db, "wannabe@example.test", admin_role.id)
    assert res.status_code == 422 and res.json()["error"]["code"] == "role_not_assignable"
    res = create(admin, db, "plain@example.test")
    assert res.json()["user"]["tier"] == "company_user"


# --- Authorization -------------------------------------------------------------------


def test_unauthenticated_requests_get_401(client: TestClient) -> None:
    for method, url in (
        ("get", USERS),
        ("post", USERS),
        ("get", ROLES),
        ("get", "/api/v1/company/permissions"),
    ):
        assert getattr(client, method)(url).status_code == 401


@pytest.mark.parametrize("category", [AccessCategory.SUPER_ADMIN, AccessCategory.COMPANY_USER])
def test_non_admins_are_denied(client: TestClient, make_user, db: Session, category) -> None:
    owner_email, _ = make_user(AccessCategory.COMPANY_ADMIN)
    owner = db.scalar(select(User).where(User.email == owner_email))
    email, password = make_user(category)
    assert login(client, email, password).status_code == 200
    h = headers(client)
    role_id = str(system_role(db, "company_user").id)
    for res in (
        client.get(USERS),
        client.get(f"{USERS}/{owner.id}"),
        client.post(
            USERS, json={"full_name": "X", "email": "x@example.test", "role_id": role_id}, headers=h
        ),
        client.patch(f"{USERS}/{owner.id}", json={"full_name": "Hacked"}, headers=h),
        client.post(f"{USERS}/{owner.id}/deactivate", headers=h),
        client.get(ROLES),
        client.post(ROLES, json={"name": "Escalate", "permissions": []}, headers=h),
        client.get("/api/v1/company/permissions"),
    ):
        assert res.status_code == 403, res.request.url
    db.expire_all()
    assert db.get(User, owner.id).full_name != "Hacked"


def test_writes_require_csrf(admin: TestClient, db: Session) -> None:
    role_id = str(system_role(db, "company_user").id)
    res = admin.post(
        USERS,
        json={"full_name": "X", "email": "x@example.test", "role_id": role_id},
        headers=ORIGIN,
    )
    assert res.status_code == 403 and res.json()["error"]["code"] == "csrf_failed"


def test_expired_subscription_blocks_user_management(admin: TestClient, db: Session) -> None:
    today = clock.utcnow().date()
    db.execute(
        update(AppSubscription).values(
            start_date=today - timedelta(days=400), expiry_date=today - timedelta(days=2)
        )
    )
    db.commit()
    res = admin.get(USERS)
    assert res.status_code == 403 and res.json()["error"]["code"] == "subscription_expired"


def test_super_admin_accounts_are_never_listed_or_reachable(
    admin: TestClient, make_user, db: Session
) -> None:
    email, _ = make_user(AccessCategory.SUPER_ADMIN)
    sa = db.scalar(select(User).where(User.email == email))
    assert email not in admin.get(USERS + "?search=super").text
    assert admin.get(f"{USERS}/{sa.id}").status_code == 404
    assert admin.post(f"{USERS}/{sa.id}/deactivate", headers=headers(admin)).status_code == 404


def test_responses_never_contain_secrets(admin: TestClient, db: Session) -> None:
    body = admin.get(USERS).text + create(admin, db, "s@example.test").text
    for needle in ("password_hash", "token_hash", "$argon2"):
        assert needle not in body


def test_admin_only_capabilities_cannot_be_granted(admin: TestClient) -> None:
    for key in ("users.view", "roles.manage", "users.deactivate"):
        res = admin.post(
            ROLES, json={"name": f"Bad {key}", "permissions": [key]}, headers=headers(admin)
        )
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "permission_not_assignable"


def test_unknown_capabilities_are_rejected_and_denied(admin: TestClient, db: Session) -> None:
    res = admin.post(
        ROLES, json={"name": "Weird", "permissions": ["shops.nuke"]}, headers=headers(admin)
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_permission"
    owner = db.scalar(select(User).where(User.email == "owner@example.test"))
    assert has_permission(db, owner, "shops.nuke") is False  # even the admin


def test_effective_permissions_follow_the_role_immediately(
    client: TestClient, admin: TestClient, make_user, db: Session
) -> None:
    other = TestClient(app, base_url="https://testserver")
    email, password = make_user(AccessCategory.COMPANY_USER)
    assert login(other, email, password).status_code == 200
    assert other.get("/api/v1/company/workspace").json()["permissions"] == ["dashboard.view"]
    role = admin.post(
        ROLES, json={"name": "Reporter", "permissions": ["reports.view"]}, headers=headers(admin)
    ).json()
    staff = db.scalar(select(User).where(User.email == email))
    assert (
        admin.patch(
            f"{USERS}/{staff.id}", json={"role_id": role["id"]}, headers=headers(admin)
        ).status_code
        == 200
    )
    # Same session, no re-login: new capability visible at once.
    assert other.get("/api/v1/company/workspace").json()["permissions"] == [
        "dashboard.view",
        "reports.view",
    ]
    admin.patch(
        f"{ROLES}/{role['id']}",
        json={"expected_version": role["version"], "permissions": []},
        headers=headers(admin),
    )
    assert other.get("/api/v1/company/workspace").json()["permissions"] == ["dashboard.view"]
    me = admin.get("/api/v1/auth/me").json()
    assert set(me["permissions"]) == set(ALL_KEYS)


def test_deactivated_user_is_cut_off_immediately(admin: TestClient, make_user, db: Session) -> None:
    other = TestClient(app, base_url="https://testserver")
    email, password = make_user(AccessCategory.COMPANY_USER)
    assert login(other, email, password).status_code == 200
    assert other.get("/api/v1/company/workspace").status_code == 200
    staff = db.scalar(select(User).where(User.email == email))
    assert admin.post(f"{USERS}/{staff.id}/deactivate", headers=headers(admin)).status_code == 200
    assert other.get("/api/v1/company/workspace").status_code == 401
    db.expire_all()
    open_sessions = db.scalar(
        select(func.count())
        .select_from(AuthenticationSession)
        .where(
            AuthenticationSession.user_id == staff.id, AuthenticationSession.revoked_at.is_(None)
        )
    )
    assert open_sessions == 0
    assert login(other, email, password).status_code == 403  # account_inactive


# --- Users: listing and editing -------------------------------------------------------


def test_search_filters_sorting_and_pagination(admin: TestClient, db: Session) -> None:
    add_company_users(db, 12, prefix="team")
    add_company_users(db, 2, active=False, prefix="former")
    page = admin.get(USERS + "?limit=5&offset=0&sort=email&order=asc").json()
    assert page["total"] == 15 and len(page["items"]) == 5
    emails = [u["email"] for u in page["items"]]
    assert emails == sorted(emails)
    assert admin.get(USERS + "?status=inactive").json()["total"] == 2
    assert admin.get(USERS + "?search=former").json()["total"] == 2
    assert admin.get(USERS + "?search=%25").json()["total"] == 0  # LIKE wildcard escaped
    role_id = system_role(db, "company_admin").id
    assert admin.get(f"{USERS}?role_id={role_id}").json()["total"] == 1
    assert admin.get(USERS + "?sort=password").status_code == 422
    assert admin.get(USERS + "?limit=500").status_code == 422


def test_role_change_and_validation(admin: TestClient, db: Session) -> None:
    created = create(admin, db, "mover@example.test").json()["user"]
    role = admin.post(
        ROLES, json={"name": "Uploader", "permissions": ["uploads.view"]}, headers=headers(admin)
    ).json()
    res = admin.patch(
        f"{USERS}/{created['id']}", json={"role_id": role["id"]}, headers=headers(admin)
    )
    assert res.status_code == 200 and res.json()["role"]["name"] == "Uploader"
    assert "company_user.role_changed" in actions(db, "company_user.")
    res = admin.patch(
        f"{USERS}/{created['id']}", json={"role_id": str(uuid.uuid4())}, headers=headers(admin)
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_role"
    res = admin.patch(f"{USERS}/{created['id']}", json={"full_name": "  "}, headers=headers(admin))
    assert res.status_code == 422


# --- Setup links ----------------------------------------------------------------------


def test_setup_link_lifecycle(admin: TestClient, client: TestClient, db: Session) -> None:
    created = create(admin, db, "newbie@example.test").json()
    token = created["setup_token"]
    user = created["user"]
    assert user["setup_pending"] is True and user["setup_link_expires_at"]
    db.expire_all()
    stored = db.scalars(select(PasswordSetupToken.token_hash)).all()
    assert stored == [hash_token(token)] and token not in str(stored)
    audit_dump = str(db.scalars(select(AuditEvent.details)).all())
    assert token not in audit_dump

    public = TestClient(app, base_url="https://testserver")
    # Cannot sign in before setting a password.
    assert login(public, "newbie@example.test", "anything-at-all-123").status_code == 401
    check = public.post("/api/v1/auth/password-setup/check", json={"token": token})
    assert check.status_code == 200 and check.json()["email"] == "ne***@example.test"
    weak = public.post(
        "/api/v1/auth/password-setup", json={"token": token, "password": "short"}, headers=ORIGIN
    )
    assert weak.status_code == 422 and weak.json()["error"]["code"] == "weak_password"
    password = random_password()
    done = public.post(
        "/api/v1/auth/password-setup", json={"token": token, "password": password}, headers=ORIGIN
    )
    assert done.status_code == 204
    again = public.post(
        "/api/v1/auth/password-setup", json={"token": token, "password": password}, headers=ORIGIN
    )
    assert again.status_code == 400 and again.json()["error"]["code"] == "invalid_setup_link"
    assert login(public, "newbie@example.test", password).status_code == 200
    assert "company_user.password_set" in actions(db, "company_user.")


def test_setup_link_expiry_and_reissue(
    admin: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = create(admin, db, "late@example.test").json()
    old = created["setup_token"]
    reissued = admin.post(f"{USERS}/{created['user']['id']}/setup-link", headers=headers(admin))
    assert reissued.status_code == 200
    new = reissued.json()["setup_token"]
    public = TestClient(app, base_url="https://testserver")
    check = "/api/v1/auth/password-setup/check"
    assert public.post(check, json={"token": old}).status_code == 400  # revoked
    assert public.post(check, json={"token": new}).status_code == 200
    later = clock.utcnow() + timedelta(hours=73)
    monkeypatch.setattr(clock, "utcnow", lambda: later)
    assert public.post(check, json={"token": new}).status_code == 400  # expired


def test_setup_completion_checks_origin(admin: TestClient, db: Session) -> None:
    token = create(admin, db, "origin@example.test").json()["setup_token"]
    public = TestClient(app, base_url="https://testserver")
    res = public.post(
        "/api/v1/auth/password-setup",
        json={"token": token, "password": random_password()},
        headers={"Origin": "https://evil.example"},
    )
    assert res.status_code == 403


def test_setup_link_not_issued_for_completed_or_admin(admin: TestClient, db: Session) -> None:
    owner = db.scalar(select(User).where(User.email == "owner@example.test"))
    assert admin.post(f"{USERS}/{owner.id}/setup-link", headers=headers(admin)).status_code == 403
    add_company_users(db, 1, prefix="done")
    done = db.scalar(select(User).where(User.email.like("done0-%")))
    res = admin.post(f"{USERS}/{done.id}/setup-link", headers=headers(admin))
    assert res.status_code == 409 and res.json()["error"]["code"] == "setup_not_pending"


# --- Roles ------------------------------------------------------------------------------


def test_system_roles_are_protected(admin: TestClient, db: Session) -> None:
    items = admin.get(ROLES).json()["items"]
    assert [r["system_key"] for r in items[:2]] == ["company_admin", "company_user"]
    admin_role = items[0]
    assert set(admin_role["permissions"]) == set(ALL_KEYS) and admin_role["active_users"] == 1
    for role in items[:2]:
        res = admin.patch(
            f"{ROLES}/{role['id']}",
            json={"expected_version": role["version"], "name": "Renamed"},
            headers=headers(admin),
        )
        assert res.status_code == 403 and res.json()["error"]["code"] == "protected_role"
        res = admin.post(
            f"{ROLES}/{role['id']}/retire",
            json={"expected_version": role["version"]},
            headers=headers(admin),
        )
        assert res.status_code == 403


def test_custom_role_create_update_and_names(admin: TestClient, db: Session) -> None:
    res = admin.post(
        ROLES,
        json={
            "name": "Shop Manager",
            "description": "Runs shops",
            "permissions": ["shops.view", "shops.edit"],
        },
        headers=headers(admin),
    )
    assert res.status_code == 201
    role = res.json()
    assert role["permissions"] == ["dashboard.view", "shops.edit", "shops.view"]
    dup = admin.post(
        ROLES, json={"name": "shop manager", "permissions": []}, headers=headers(admin)
    )
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "role_name_taken"
    upd = admin.patch(
        f"{ROLES}/{role['id']}",
        json={
            "expected_version": role["version"],
            "permissions": ["shops.view"],
            "name": "Shop Lead",
        },
        headers=headers(admin),
    )
    assert upd.status_code == 200 and upd.json()["version"] == role["version"] + 1
    stale = admin.patch(
        f"{ROLES}/{role['id']}",
        json={"expected_version": role["version"], "name": "Again"},
        headers=headers(admin),
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_role"
    trail = actions(db, "company_role.")
    assert {
        "company_role.created",
        "company_role.updated",
        "company_role.permissions_changed",
    } <= set(trail)


def test_retiring_an_assigned_role_requires_reassignment(admin: TestClient, db: Session) -> None:
    role = admin.post(
        ROLES, json={"name": "Temp", "permissions": []}, headers=headers(admin)
    ).json()
    user = create(admin, db, "temp@example.test", uuid.UUID(role["id"])).json()["user"]
    res = admin.post(
        f"{ROLES}/{role['id']}/retire",
        json={"expected_version": role["version"]},
        headers=headers(admin),
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "role_in_use"
    default = system_role(db, "company_user")
    res = admin.post(
        f"{ROLES}/{role['id']}/retire",
        json={"expected_version": role["version"], "reassign_to_role_id": str(default.id)},
        headers=headers(admin),
    )
    assert res.status_code == 200 and res.json()["is_active"] is False
    assert admin.get(f"{USERS}/{user['id']}").json()["role"]["name"] == "Company User"
    again = create(admin, db, "late@example.test", uuid.UUID(role["id"]))
    assert again.status_code == 422 and again.json()["error"]["code"] == "role_inactive"
    assert "company_role.retired" in actions(db, "company_role.")


def test_retired_role_grants_nothing_beyond_the_baseline(db: Session) -> None:
    role = CompanyRole(name="Ghost", is_active=False, version=1)
    db.add(role)
    db.flush()
    from app.models import CompanyRolePermission

    db.add(CompanyRolePermission(role_id=role.id, permission="reports.view"))
    user = User(
        email="ghost@example.test",
        full_name="Ghost",
        password_hash=hash_password("x"),
        access_category=AccessCategory.COMPANY_USER,
        company_role_id=role.id,
    )
    db.add(user)
    db.commit()
    assert has_permission(db, user, "reports.view") is False
    assert has_permission(db, user, "dashboard.view") is True


def test_permission_catalog_marks_unavailable_modules(admin: TestClient) -> None:
    modules = {m["key"]: m for m in admin.get("/api/v1/company/permissions").json()["modules"]}
    assert modules["dashboard"]["available"] is True
    assert modules["users"]["admin_only"] is True and modules["roles"]["admin_only"] is True
    assert modules["shops"]["available"] is True  # Shop Management (Phase 3)
    assert modules["uploads"]["available"] is True  # Excel Uploads (Phase 4)
    for key in ("approvals", "fbr_sync", "reports"):
        assert modules[key]["available"] is False
    assert {c["key"] for c in modules["fbr_sync"]["capabilities"]} == {
        "fbr_sync.view",
        "fbr_sync.control",
        "fbr_sync.retry",
    }


def test_bootstrap_style_inserts_get_the_system_role(db: Session) -> None:
    db.add(
        User(
            email="cli@example.test",
            full_name="CLI",
            password_hash="x",
            access_category=AccessCategory.COMPANY_USER,
        )
    )
    db.commit()
    user = db.scalar(select(User).where(User.email == "cli@example.test"))
    assert user.company_role_id == system_role(db, "company_user").id
