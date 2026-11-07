"""Phase 4.1: upload permissions per action, shop scope, revocation and duplicates.

Mirrors the manual QA of a Company User ("Sales Operator" with CH-001 assigned,
CH-002 not assigned) on disposable data, and pins down the role rules:
View / Upload / Replace draft, and the not-yet-built Delete draft and Submit.
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.models import (
    AccessCategory,
    CompanyRolePermission,
    UploadBatch,
    UploadRevision,
    User,
    UserShopAccess,
    UserShopAssignment,
)
from app.services import upload_storage
from tests.test_uploads import (  # noqa: F401  (_empty_storage is an autouse fixture)
    BASE,
    DAY,
    GOOD_ROW,
    UPLOADER,
    _empty_storage,
    add_shop,
    h,
    preview,
    replace,
    save,
    signed_in,
    staff,
    xlsx,
)

pytestmark = pytest.mark.usefixtures("valid_subscription")


@pytest.fixture
def admin(make_user) -> TestClient:
    return signed_in(make_user, AccessCategory.COMPANY_ADMIN, "owner@example.test")


REV1 = xlsx([[DAY, *GOOD_ROW[1:]]])  # 2 x 1000 at 18% -> net 2,360.00
REV2 = xlsx([[DAY, GOOD_ROW[1], "Jeans", "Ali Raza", "0123456-7", 3, 1000, 3000]])  # net 3,540.00


def two_revisions(admin: TestClient, shop) -> str:
    batch = save(admin, shop, REV1, name="rev-1.xlsx").json()
    params = {
        "filename": "rev-2.xlsx",
        "expected_checksum": upload_storage.checksum(REV2),
        "expected_revision": 1,
        "expected_tax_rate": "18",
    }
    res = admin.post(f"{BASE}/{batch['id']}/replace", params=params, content=REV2, headers=h(admin))
    assert res.status_code == 200, res.text
    return batch["id"]


# --- Assigned vs unassigned shop (the "Hamza" scenario) ---------------------------------


def test_company_user_reaches_only_the_assigned_shop(
    admin: TestClient, db: Session, make_user
) -> None:
    ch1, ch2 = add_shop(db, "CH-001"), add_shop(db, "CH-002")
    own = two_revisions(admin, ch1)
    foreign = two_revisions(admin, ch2)
    operator = staff(db, make_user, UPLOADER, shops=[ch1])

    # CH-001: list, detail, records and both originals.
    listed = operator.get(BASE).json()
    assert [i["shop"]["code"] for i in listed["items"]] == ["CH-001"]  # CH-002 never listed
    assert operator.get(BASE, params={"shop": str(ch1.id)}).status_code == 200
    assert operator.get(f"{BASE}/{own}").status_code == 200
    assert operator.get(f"{BASE}/{own}/records", params={"revision": 1}).status_code == 200
    assert operator.get(f"{BASE}/{own}/revisions/1/original").content == REV1
    assert operator.get(f"{BASE}/{own}/revisions/2/original").content == REV2

    # CH-002: every read, download and write is refused as "not found" (no existence leak).
    for path in (
        f"{BASE}/{foreign}",
        f"{BASE}/{foreign}/records",
        f"{BASE}/{foreign}/records?revision=1",
        f"{BASE}/{foreign}/revisions/1/original",
        f"{BASE}/{foreign}/revisions/2/original",
    ):
        assert operator.get(path).status_code == 404, path
    assert operator.get(BASE, params={"shop": str(ch2.id)}).status_code == 404
    other_day = DAY - timedelta(days=1)
    assert preview(operator, ch2, xlsx(), day=other_day).status_code == 404
    assert save(operator, ch2, xlsx([[other_day, *GOOD_ROW[1:]]]), day=other_day).status_code == 404
    assert replace(operator, foreign, xlsx(), 2).status_code == 404
    # Manipulated identifiers are rejected, never widened to "all shops".
    assert operator.get(BASE, params={"shop": "not-a-uuid"}).status_code == 422
    assert preview(operator, "00000000-0000-0000-0000-000000000000", xlsx()).status_code == 404

    # Nothing about CH-002 changed.
    assert (
        db.scalar(
            select(func.count())
            .select_from(UploadRevision)
            .where(UploadRevision.batch_id == foreign)
        )
        == 2
    )


def test_company_admin_covers_every_shop(admin: TestClient, db: Session) -> None:
    ch1, ch2 = add_shop(db, "CH-001"), add_shop(db, "CH-002")
    ids = [two_revisions(admin, ch1), two_revisions(admin, ch2)]
    assert admin.get(BASE).json()["total"] == 2
    for batch_id in ids:
        assert admin.get(f"{BASE}/{batch_id}/revisions/1/original").status_code == 200


# --- Revision originals -------------------------------------------------------------------


def test_each_revision_downloads_its_own_original(admin: TestClient, db: Session) -> None:
    shop = add_shop(db, "CH-001")
    batch_id = two_revisions(admin, shop)
    revisions = admin.get(f"{BASE}/{batch_id}").json()["revisions"]
    assert [(r["revision_number"], r["is_current"]) for r in revisions] == [(2, True), (1, False)]
    expected = {1: (REV1, "rev-1.xlsx", "2360.00"), 2: (REV2, "rev-2.xlsx", "3540.00")}
    for number, (content, name, first_net) in expected.items():
        res = admin.get(f"{BASE}/{batch_id}/revisions/{number}/original")
        assert res.status_code == 200
        assert res.content == content
        assert upload_storage.checksum(res.content) == next(
            r["checksum"] for r in revisions if r["revision_number"] == number
        )
        disposition = res.headers["content-disposition"]
        assert disposition.startswith("attachment;") and f'filename="{name}"' in disposition
        assert (
            res.headers["cache-control"].startswith("no-store")
            or "private" in res.headers["cache-control"]
        )
        records = admin.get(f"{BASE}/{batch_id}/records", params={"revision": number}).json()
        assert records["items"][0]["net_amount"] == first_net
    # Revision 1 stays as it was: rows, totals and file (append-only).
    rev1 = db.scalar(
        select(UploadRevision).where(
            UploadRevision.batch_id == batch_id, UploadRevision.revision_number == 1
        )
    )
    assert rev1 is not None and str(rev1.total_net_amount) == "2360.00"


# --- Role permissions per action -----------------------------------------------------------


def test_view_only_can_read_but_not_upload_or_replace(
    admin: TestClient, db: Session, make_user
) -> None:
    shop = add_shop(db, "CH-001")
    batch_id = two_revisions(admin, shop)
    viewer = staff(db, make_user, ["uploads.view"], shops=[shop])
    assert viewer.get(BASE).json()["total"] == 1
    assert viewer.get(f"{BASE}/{batch_id}/revisions/1/original").status_code == 200
    item = viewer.get(f"{BASE}/{batch_id}").json()["batch"]
    assert item["can_replace"] is False  # the UI hides Replace Draft
    other_day = DAY - timedelta(days=1)
    assert preview(viewer, shop, xlsx(), day=other_day).status_code == 403
    assert save(viewer, shop, xlsx([[other_day, *GOOD_ROW[1:]]]), day=other_day).status_code == 403
    assert replace(viewer, batch_id, xlsx(), 2).status_code == 403


def test_upload_without_replace_draft_cannot_replace(
    admin: TestClient, db: Session, make_user
) -> None:
    shop = add_shop(db, "CH-001")
    batch_id = two_revisions(admin, shop)
    uploader = staff(db, make_user, ["uploads.view", "uploads.upload"], shops=[shop])
    other_day = DAY - timedelta(days=1)
    assert (
        save(uploader, shop, xlsx([[other_day, *GOOD_ROW[1:]]]), day=other_day).status_code == 201
    )
    dup = preview(uploader, shop, xlsx()).json()["existing"]
    assert dup["id"] == batch_id and dup["can_replace"] is False
    assert replace(uploader, batch_id, xlsx(), 2).status_code == 403
    assert uploader.get(f"{BASE}/{batch_id}").json()["batch"]["can_replace"] is False


@pytest.mark.parametrize(
    "permissions",
    [
        ["uploads.edit_draft"],
        ["uploads.edit_draft", "uploads.upload"],  # no View
        ["uploads.edit_draft", "uploads.view"],  # no Upload
    ],
)
def test_replace_draft_alone_opens_no_way_around_view_or_upload(
    admin: TestClient, db: Session, make_user, permissions: list[str]
) -> None:
    shop = add_shop(db, "CH-001")
    batch_id = two_revisions(admin, shop)
    user = staff(db, make_user, permissions, shops=[shop])
    assert replace(user, batch_id, xlsx(), 2).status_code == 403
    if "uploads.view" not in permissions:
        assert user.get(BASE).status_code == 403
        assert user.get(f"{BASE}/{batch_id}").status_code == 403
    assert db.scalar(select(UploadBatch.current_revision).where(UploadBatch.id == batch_id)) == 2


def test_view_upload_and_replace_draft_together_can_replace(
    admin: TestClient, db: Session, make_user
) -> None:
    shop = add_shop(db, "CH-001")
    batch_id = two_revisions(admin, shop)
    operator = staff(db, make_user, UPLOADER, shops=[shop])
    assert operator.get(f"{BASE}/{batch_id}").json()["batch"]["can_replace"] is True
    assert replace(operator, batch_id, xlsx(), 2).status_code == 200


def test_unbuilt_delete_and_submit_permissions_expose_nothing(
    admin: TestClient, db: Session, make_user
) -> None:
    shop = add_shop(db, "CH-001")
    batch_id = two_revisions(admin, shop)
    user = staff(
        db, make_user, ["uploads.view", "uploads.delete_draft", "uploads.submit"], shops=[shop]
    )
    assert user.delete(f"{BASE}/{batch_id}", headers=h(user)).status_code == 405
    for action in ("submit", "delete", "approve", "accept"):
        assert user.post(f"{BASE}/{batch_id}/{action}", headers=h(user)).status_code in {404, 405}
    assert replace(user, batch_id, xlsx(), 2).status_code == 403  # not a Replace right either
    batch = db.scalar(select(UploadBatch).where(UploadBatch.id == batch_id))
    assert batch is not None and batch.status == "draft" and batch.current_revision == 2


def test_module_permission_alone_never_reaches_an_unassigned_shop(
    admin: TestClient, db: Session, make_user
) -> None:
    ch1, ch2 = add_shop(db, "CH-001"), add_shop(db, "CH-002")
    batch_id = two_revisions(admin, ch2)
    user = staff(db, make_user, UPLOADER, shops=[ch1])
    assert user.get(f"{BASE}/{batch_id}").status_code == 404
    nobody = staff(db, make_user, [], shops=[ch1, ch2])  # assignment alone: no module access
    assert nobody.get(BASE).status_code == 403
    assert nobody.get(f"{BASE}/{batch_id}").status_code == 403


# --- Changes take effect on the next request ---------------------------------------------


def test_revocations_apply_on_the_next_request(admin: TestClient, db: Session, make_user) -> None:
    ch1 = add_shop(db, "CH-001")
    batch_id = two_revisions(admin, ch1)
    operator = staff(db, make_user, UPLOADER, shops=[ch1])
    assert operator.get(f"{BASE}/{batch_id}").status_code == 200

    # Role permission removed -> refused at once (no cached rights).
    db.execute(
        delete(CompanyRolePermission).where(
            CompanyRolePermission.role_id == operator.role_id,  # type: ignore[attr-defined]
            CompanyRolePermission.permission == "uploads.upload",
        )
    )
    db.commit()
    other_day = DAY - timedelta(days=1)
    assert preview(operator, ch1, xlsx(), day=other_day).status_code == 403
    assert operator.get(f"{BASE}/{batch_id}").json()["batch"]["can_replace"] is False

    # Shop assignment removed -> the shop's data disappears.
    db.execute(
        delete(UserShopAssignment).where(UserShopAssignment.user_id == operator.user_id)  # type: ignore[attr-defined]
    )
    db.execute(
        update(UserShopAccess)
        .where(UserShopAccess.user_id == operator.user_id)  # type: ignore[attr-defined]
        .values(access_mode="none", version=UserShopAccess.version + 1)
    )
    db.commit()
    assert operator.get(f"{BASE}/{batch_id}").status_code == 404
    assert operator.get(BASE).json()["total"] == 0

    # Deactivated account -> signed out.
    db.execute(update(User).where(User.id == operator.user_id).values(is_active=False))  # type: ignore[attr-defined]
    db.commit()
    assert operator.get(BASE).status_code == 401


# --- Duplicate protection -------------------------------------------------------------------


def test_duplicates_never_create_a_second_batch_or_touch_history(
    admin: TestClient, db: Session, make_user
) -> None:
    ch1, ch2 = add_shop(db, "CH-001"), add_shop(db, "CH-002")
    batch_id = two_revisions(admin, ch1)
    before = db.scalars(select(UploadRevision.checksum_sha256).order_by(UploadRevision.id)).all()

    # The warning is information only: a preview of the duplicate saves nothing.
    check = preview(admin, ch1, xlsx()).json()
    assert check["existing"]["id"] == batch_id and check["can_save"] is False
    # A direct "new upload" for the same shop and date is refused, not turned into a replacement.
    dup = save(admin, ch1, xlsx())
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "upload_exists"

    assert db.scalar(select(func.count()).select_from(UploadBatch)) == 1
    assert db.scalar(select(UploadBatch.current_revision).where(UploadBatch.id == batch_id)) == 2
    db.expire_all()
    after = db.scalars(select(UploadRevision.checksum_sha256).order_by(UploadRevision.id)).all()
    assert after == before

    # Other shop / other date are separate batches.
    assert save(admin, ch2, xlsx()).status_code == 201
    other_day = DAY - timedelta(days=1)
    assert save(admin, ch1, xlsx([[other_day, *GOOD_ROW[1:]]]), day=other_day).status_code == 201
    assert db.scalar(select(func.count()).select_from(UploadBatch)) == 3


def test_a_batch_past_draft_cannot_be_replaced_by_anyone(admin: TestClient, db: Session) -> None:
    shop = add_shop(db, "CH-001")
    batch_id = two_revisions(admin, shop)
    for status in ("wait_for_approval", "accepted", "rejected"):
        db.execute(update(UploadBatch).where(UploadBatch.id == batch_id).values(status=status))
        db.commit()
        res = replace(admin, batch_id, xlsx(), 2)
        assert res.status_code == 409 and res.json()["error"]["code"] == "upload_not_draft"
        assert admin.get(f"{BASE}/{batch_id}").json()["batch"]["can_replace"] is False
        assert save(admin, shop, xlsx()).status_code == 409
    assert db.scalar(select(UploadBatch.current_revision).where(UploadBatch.id == batch_id)) == 2
