"""Phase 4.2: shop-wise Sales Tax %, the 8-column template and tax snapshots.

Tax exclusive: Sales Tax = Amount x shop rate / 100 (ROUND_HALF_UP per row),
Net = Amount + Sales Tax. Every revision keeps the rate it was calculated
with; a shop rate change never touches saved uploads, and a Draft
replacement keeps the Draft's rate.
"""

import io
import threading
from datetime import time, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import get_engine
from app.models import (
    AccessCategory,
    AuditEvent,
    SalesRecord,
    Shop,
    UploadBatch,
    UploadRevision,
    User,
)
from app.services import excel_sales, upload_storage
from tests.conftest import csrf_header
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
    stored_files,
    xlsx,
)

pytestmark = pytest.mark.usefixtures("valid_subscription")
SHOPS = "/api/v1/company/shops"


def jh(client: TestClient) -> dict[str, str]:
    """JSON requests: CSRF + Origin, no Excel content type."""
    return {**csrf_header(client), "Origin": "http://localhost:3000"}


DASHBOARD = "/api/v1/company/dashboard/summary"


@pytest.fixture
def admin(make_user) -> TestClient:
    return signed_in(make_user, AccessCategory.COMPANY_ADMIN, "owner@example.test")


def shop_payload(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "name": "Main Store",
        "branch_name": "Gulberg",
        "code": "TAX-01",
        "pos_id": "700001",
        "sales_tax_rate": "18",
    }
    data.update(overrides)
    return data


def patch_shop(client: TestClient, shop_id: object, version: int, **fields: object):
    return client.patch(
        f"{SHOPS}/{shop_id}", json={"expected_version": version, **fields}, headers=jh(client)
    )


def legacy_workbook(rows: list[list[object]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws.append(list(excel_sales.LEGACY_HEADERS))
    for row in rows:
        ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def legacy_batch(db: Session, shop: Shop, rates: list[str], *, day=DAY) -> UploadBatch:
    """A Draft saved with the previous 10-column template (as migration 0013 left it)."""
    rows = [
        [day, time(10, 0), "Old Customer", None, 1, 1000, 1000, Decimal(r), Decimal(r) * 10, 0]
        for r in rates
    ]
    stored = upload_storage.save(legacy_workbook(rows))
    taxes = [(Decimal(r) * 10).quantize(Decimal("0.01")) for r in rates]
    uniform = len(set(rates)) == 1
    batch = UploadBatch(
        shop_id=shop.id,
        sales_date=day,
        status="draft",
        current_revision=1,
        total_records=len(rates),
        total_amount=Decimal(1000 * len(rates)),
        total_sales_tax=sum(taxes),
        total_net_amount=Decimal(1000 * len(rates)) + sum(taxes),
    )
    db.add(batch)
    db.flush()
    revision = UploadRevision(
        batch_id=batch.id,
        revision_number=1,
        original_filename="old-template.xlsx",
        storage_key=stored.key,
        checksum_sha256=stored.checksum_sha256,
        file_size=stored.size,
        total_records=len(rates),
        total_amount=batch.total_amount,
        total_sales_tax=batch.total_sales_tax,
        total_net_amount=batch.total_net_amount,
        template_format="legacy_10col",
        applied_sales_tax_rate=Decimal(rates[0]) if uniform else None,
        tax_rate_source="legacy_rows" if uniform else "legacy_mixed",
    )
    db.add(revision)
    db.flush()
    for i, (rate, tax) in enumerate(zip(rates, taxes, strict=True)):
        db.add(
            SalesRecord(
                revision_id=revision.id,
                batch_id=batch.id,
                shop_id=shop.id,
                excel_row=i + 2,
                sale_date=day,
                sale_time=time(10, 0),
                item=None,  # the old template had no Item column
                customer_name="Old Customer",
                quantity=Decimal(1),
                rate=Decimal(1000),
                amount=Decimal(1000),
                tax_percent=Decimal(rate),
                tax_amount=tax,
                net_amount=Decimal(1000) + tax,
            )
        )
    db.commit()
    return batch


# --- Shop Sales Tax % ------------------------------------------------------------------------


def test_a_new_shop_requires_a_valid_sales_tax_rate(admin: TestClient, db: Session) -> None:
    missing = admin.post(SHOPS, json=shop_payload(sales_tax_rate=None), headers=jh(admin))
    assert (
        missing.status_code == 422 and missing.json()["error"]["code"] == "invalid_sales_tax_rate"
    )
    for bad in ("-1", "100.01", "101", "17.555", "abc", "1e2", "18,5", " "):
        res = admin.post(SHOPS, json=shop_payload(sales_tax_rate=bad), headers=jh(admin))
        assert res.status_code == 422, bad
        assert res.json()["error"]["code"] == "invalid_sales_tax_rate", bad
    assert db.scalar(select(func.count()).select_from(Shop)) == 0
    for code, given, stored in (
        ("T0", "0", "0.00"),
        ("T1", "17.5", "17.50"),
        ("T2", "100", "100.00"),
    ):
        res = admin.post(
            SHOPS,
            json=shop_payload(code=code, pos_id=f"P{code}", sales_tax_rate=given),
            headers=jh(admin),
        )
        assert res.status_code == 201, res.text
        assert res.json()["sales_tax_rate"] == stored  # exact decimal text, 0% allowed
    created = db.scalars(select(AuditEvent).where(AuditEvent.action == "shop.created")).all()
    assert sorted(e.details["sales_tax_rate"] for e in created) == ["0.00", "100.00", "17.50"]


def test_shops_created_before_the_tax_field_stay_intact_and_unconfigured(
    admin: TestClient, db: Session
) -> None:
    old = add_shop(db, "CH-001", rate=None)  # as migration 0013 leaves existing shops
    listed = admin.get(SHOPS).json()["items"][0]
    assert listed["code"] == "CH-001" and listed["sales_tax_rate"] is None
    # Editing other fields keeps it unconfigured; setting the rate is allowed.
    res = patch_shop(admin, old.id, 1, branch_name="New Branch")
    assert res.status_code == 200 and res.json()["sales_tax_rate"] is None
    res = patch_shop(admin, old.id, 2, sales_tax_rate="18")
    assert res.status_code == 200 and res.json()["sales_tax_rate"] == "18.00"
    # Once configured it can change but never be removed.
    removed = patch_shop(admin, old.id, 3, sales_tax_rate=None)
    assert (
        removed.status_code == 422 and removed.json()["error"]["code"] == "invalid_sales_tax_rate"
    )


def test_rate_changes_are_audited_once_with_previous_and_new_rate(
    admin: TestClient, db: Session
) -> None:
    shop = add_shop(db, "CH-001")
    assert patch_shop(admin, shop.id, 1, sales_tax_rate="18.00").json()["version"] == 1  # no-op
    res = patch_shop(admin, shop.id, 1, sales_tax_rate="17")
    assert res.status_code == 200 and res.json()["sales_tax_rate"] == "17.00"
    events = db.scalars(select(AuditEvent).where(AuditEvent.action == "shop.updated")).all()
    assert len(events) == 1  # the no-op wrote nothing
    details = events[0].details
    assert details["changed"] == ["sales_tax_rate"]
    assert details["sales_tax_rate"] == {"previous": "18.00", "new": "17.00"}
    assert "token" not in str(details).lower()


def test_only_shop_editors_can_change_the_rate(admin: TestClient, db: Session, make_user) -> None:
    shop = add_shop(db, "CH-001")
    operator = staff(db, make_user, UPLOADER, shops=[shop])  # can upload, cannot edit shops
    res = patch_shop(operator, shop.id, 1, sales_tax_rate="0")
    assert res.status_code == 403
    viewer = staff(db, make_user, ["shops.view"], mode="all")
    assert patch_shop(viewer, shop.id, 1, sales_tax_rate="0").status_code == 403
    root = signed_in(make_user, AccessCategory.SUPER_ADMIN)
    assert root.get(SHOPS).status_code == 403  # no shop tax settings for the Super Admin
    db.refresh(shop)
    assert shop.sales_tax_rate == Decimal("18.00")


# --- Uploads use the shop rate -------------------------------------------------------------


def test_an_unconfigured_shop_cannot_take_a_new_upload(admin: TestClient, db: Session) -> None:
    shop = add_shop(db, "CH-001", rate=None)
    for res in (preview(admin, shop, xlsx()), save(admin, shop, xlsx())):
        assert res.status_code == 409
        assert res.json()["error"] == {
            "code": "sales_tax_not_configured",
            "message": "Sales Tax % is not configured for this shop. Configure it in Shop "
            "Management before uploading.",
        }
    assert db.scalar(select(func.count()).select_from(UploadBatch)) == 0
    assert stored_files() == set()


def test_each_shop_uses_its_own_rate_and_preview_matches_saved(
    admin: TestClient, db: Session
) -> None:
    standard = add_shop(db, "STD", rate=Decimal("18"))
    reduced = add_shop(db, "RED", rate=Decimal("17.5"))
    exempt = add_shop(db, "ZERO", rate=Decimal("0"))
    data = xlsx([GOOD_ROW, [DAY, "11:00", "Fabric", None, None, 3, "33.3333", "100.00"]])
    expected = {
        standard: ("18.00", "2100.00", "378.00", "2478.00"),
        reduced: ("17.50", "2100.00", "367.50", "2467.50"),
        exempt: ("0.00", "2100.00", "0.00", "2100.00"),
    }
    for shop, (rate, amount, tax, net) in expected.items():
        body = preview(admin, shop, data).json()
        assert body["applied_sales_tax_rate"] == rate and body["tax_rate_source"] == "shop"
        assert body["totals"] == {"amount": amount, "sales_tax": tax, "net_amount": net}
        saved = save(admin, shop, data, rate=rate)
        assert saved.status_code == 201, saved.text
        assert saved.json()["totals"] == body["totals"]  # preview totals == saved totals
        rows = db.scalars(
            select(SalesRecord)
            .where(SalesRecord.shop_id == shop.id)
            .order_by(SalesRecord.excel_row)
        ).all()
        assert {r.tax_percent for r in rows} == {Decimal(rate)}
        assert [r.item for r in rows] == ["Cotton Shirt", "Fabric"]


def test_the_previous_10_column_template_is_refused_for_new_uploads(
    admin: TestClient, db: Session
) -> None:
    shop = add_shop(db, "CH-001")
    old = legacy_workbook([[DAY, "10:00", None, None, 2, 1000, 2000, 18, 360, 2360]])
    res = preview(admin, shop, old)
    assert res.status_code == 422 and res.json()["error"]["code"] == "legacy_template"
    assert "8-column template" in res.json()["error"]["message"]
    assert save(admin, shop, old).json()["error"]["code"] == "legacy_template"


def test_a_rate_change_after_the_preview_is_never_saved_silently(
    admin: TestClient, db: Session
) -> None:
    shop = add_shop(db, "CH-001")
    data = xlsx()
    checked = preview(admin, shop, data).json()
    assert (
        checked["applied_sales_tax_rate"] == "18.00"
        and checked["totals"]["net_amount"] == "2360.00"
    )
    assert patch_shop(admin, shop.id, 1, sales_tax_rate="17").status_code == 200
    stale = save(admin, shop, data, rate=checked["applied_sales_tax_rate"])
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "tax_rate_changed"
    assert "from 18% to 17%" in stale.json()["error"]["message"]
    assert db.scalar(select(func.count()).select_from(UploadBatch)) == 0
    assert stored_files() == set()  # the stored file was discarded
    # Without a preview rate the save is refused too.
    assert save(admin, shop, data, rate="").json()["error"]["code"] == "preview_mismatch"
    again = preview(admin, shop, data).json()
    assert again["applied_sales_tax_rate"] == "17.00" and again["totals"]["net_amount"] == "2340.00"
    ok = save(admin, shop, data, rate=again["applied_sales_tax_rate"])
    assert ok.status_code == 201 and ok.json()["totals"]["net_amount"] == "2340.00"


def test_a_rate_change_racing_a_save_is_serialized(admin: TestClient, db: Session) -> None:
    """The shop row lock: a save waiting behind an uncommitted rate change sees it."""
    shop = add_shop(db, "CH-001")
    shop_id = shop.id
    data = xlsx()
    other = sessionmaker(bind=get_engine())()
    other.execute(text("SET lock_timeout = '20s'"))
    locked = other.get(Shop, shop_id, with_for_update=True)  # an edit in progress
    assert locked is not None
    locked.sales_tax_rate = Decimal("17")
    other.flush()
    results: list[object] = []
    client = TestClient(app_for_threads(), base_url="https://testserver")
    client.cookies.update(admin.cookies)

    def saver() -> None:
        results.append(save(client, shop, data, rate="18"))

    thread = threading.Thread(target=saver)
    thread.start()
    thread.join(timeout=2)
    assert thread.is_alive()  # blocked on the shop row lock, not saved at the old rate
    other.commit()
    other.close()
    thread.join(timeout=30)
    res = results[0]
    assert res.status_code == 409 and res.json()["error"]["code"] == "tax_rate_changed"  # type: ignore[attr-defined]
    assert db.scalar(select(func.count()).select_from(UploadBatch)) == 0


def app_for_threads():
    from app.main import app

    return app


# --- Historical snapshots --------------------------------------------------------------------


def test_saved_uploads_keep_their_rate_after_the_shop_rate_changes(
    admin: TestClient, db: Session
) -> None:
    shop = add_shop(db, "CH-001")
    batch = save(admin, shop, xlsx()).json()
    before = admin.get(f"{BASE}/{batch['id']}").json()
    records_before = admin.get(f"{BASE}/{batch['id']}/records").json()
    dash_before = admin.get(DASHBOARD).json()["sales_overview"]
    assert patch_shop(admin, shop.id, 1, sales_tax_rate="17").status_code == 200

    after = admin.get(f"{BASE}/{batch['id']}").json()
    assert after == before  # totals, applied rate and revisions unchanged
    assert after["batch"]["applied_sales_tax_rate"] == "18.0000"
    assert after["revisions"][0]["tax_rate_source"] == "shop"
    assert admin.get(f"{BASE}/{batch['id']}/records").json() == records_before
    assert (
        admin.get(DASHBOARD).json()["sales_overview"] == dash_before
    )  # never re-joined to the rate


def test_replacement_keeps_the_drafts_rate_not_the_shops_current_rate(
    admin: TestClient, db: Session
) -> None:
    shop = add_shop(db, "CH-001")
    batch = save(admin, shop, xlsx()).json()  # saved at 18%
    assert patch_shop(admin, shop.id, 1, sales_tax_rate="17").status_code == 200
    new_file = xlsx([GOOD_ROW, GOOD_ROW])
    checked = preview(admin, shop, new_file).json()
    assert checked["applied_sales_tax_rate"] == "18.0000"  # the Draft's rate, not 17%
    assert checked["tax_rate_source"] == "draft" and checked["totals"]["sales_tax"] == "720.00"
    wrong = replace(admin, batch["id"], new_file, 1, rate="17")
    assert wrong.status_code == 409 and wrong.json()["error"]["code"] == "tax_rate_changed"
    res = replace(admin, batch["id"], new_file, 1, rate=checked["applied_sales_tax_rate"])
    assert res.status_code == 200, res.text
    assert res.json()["totals"] == {
        "amount": "4000.00",
        "sales_tax": "720.00",
        "net_amount": "4720.00",
    }
    revisions = admin.get(f"{BASE}/{batch['id']}").json()["revisions"]
    assert [
        (r["revision_number"], r["applied_sales_tax_rate"], r["tax_rate_source"]) for r in revisions
    ] == [
        (2, "18.0000", "draft"),
        (1, "18.0000", "shop"),
    ]
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "upload.replaced"))
    assert event is not None and event.details["applied_sales_tax_rate"] == "18.0000"
    assert event.details["tax_rate_source"] == "draft"
    created = db.scalar(select(AuditEvent).where(AuditEvent.action == "upload.created"))
    assert created is not None and created.details["applied_sales_tax_rate"] == "18.00"
    assert created.details["template_format"] == "standard_8col"


# --- Legacy 10-column revisions -------------------------------------------------------------


def test_legacy_revisions_stay_viewable_and_downloadable(admin: TestClient, db: Session) -> None:
    shop = add_shop(db, "CH-001", rate=None)
    batch = legacy_batch(db, shop, ["18", "18"])
    key, checksum = db.execute(
        select(UploadRevision.storage_key, UploadRevision.checksum_sha256)
    ).one()
    detail = admin.get(f"{BASE}/{batch.id}").json()
    assert detail["batch"]["template_format"] == "legacy_10col"
    assert detail["batch"]["applied_sales_tax_rate"] == "18.0000"
    assert detail["batch"]["totals"] == {
        "amount": "2000.00",
        "sales_tax": "360.00",
        "net_amount": "2360.00",
    }
    rows = admin.get(f"{BASE}/{batch.id}/records").json()["items"]
    assert [r["item"] for r in rows] == [None, None]  # never invented
    original = admin.get(f"{BASE}/{batch.id}/revisions/1/original")
    assert original.status_code == 200 and upload_storage.checksum(original.content) == checksum
    assert db.scalar(select(UploadRevision.storage_key)) == key


def test_a_uniform_legacy_draft_is_replaced_at_its_own_rate(admin: TestClient, db: Session) -> None:
    shop = add_shop(db, "CH-001", rate=None)  # shop rate still unconfigured
    batch = legacy_batch(db, shop, ["18", "18"])
    new_file = xlsx()
    checked = preview(admin, shop, new_file).json()
    assert checked["applied_sales_tax_rate"] == "18.0000" and checked["tax_rate_source"] == "draft"
    res = replace(admin, str(batch.id), new_file, 1, rate="18.0000")
    assert res.status_code == 200, res.text
    revisions = admin.get(f"{BASE}/{batch.id}").json()["revisions"]
    assert [(r["template_format"], r["tax_rate_source"]) for r in revisions] == [
        ("standard_8col", "draft"),
        ("legacy_10col", "legacy_rows"),
    ]
    old_rows = admin.get(f"{BASE}/{batch.id}/records", params={"revision": 1}).json()["items"]
    assert [r["item"] for r in old_rows] == [None, None] and old_rows[0]["tax_amount"] == "180.00"


def test_mixed_rate_legacy_data_is_shown_honestly_and_not_replaced(
    admin: TestClient, db: Session
) -> None:
    shop = add_shop(db, "CH-001")
    batch = legacy_batch(db, shop, ["18", "17"])
    detail = admin.get(f"{BASE}/{batch.id}").json()
    assert detail["batch"]["applied_sales_tax_rate"] is None
    assert detail["batch"]["tax_rate_source"] == "legacy_mixed"
    assert detail["batch"]["can_replace"] is False
    rows = admin.get(f"{BASE}/{batch.id}/records").json()["items"]
    assert [r["tax_percent"] for r in rows] == ["18.0000", "17.0000"]  # per-row rates kept
    res = preview(admin, shop, xlsx())
    assert res.status_code == 409 and res.json()["error"]["code"] == "draft_tax_rate_unknown"
    refused = replace(admin, str(batch.id), xlsx(), 1, rate="18")
    assert (
        refused.status_code == 409 and refused.json()["error"]["code"] == "draft_tax_rate_unknown"
    )
    assert db.scalar(select(func.count()).select_from(UploadRevision)) == 1


# --- Dashboard --------------------------------------------------------------------------------


def test_dashboard_sums_current_revisions_per_scope(
    admin: TestClient, db: Session, make_user
) -> None:
    a = add_shop(db, "A", rate=Decimal("18"))
    b = add_shop(db, "B", rate=Decimal("10"))
    first = save(admin, a, xlsx()).json()  # 2,360.00
    replace(admin, first["id"], xlsx([GOOD_ROW, GOOD_ROW]), 1)  # now 4,720.00 (not added)
    save(admin, b, xlsx(), rate="10")  # 2,200.00
    everything = admin.get(DASHBOARD).json()["sales_overview"]
    assert (everything["uploads"], everything["records"]) == (2, 3)
    assert everything["total_sales_tax"] == "920.00" and everything["total_net_amount"] == "6920.00"
    only_b = admin.get(DASHBOARD, params={"shop_id": str(b.id)}).json()["sales_overview"]
    assert only_b["total_net_amount"] == "2200.00" and only_b["records"] == 1
    # A Company User sees only assigned shops' uploads.
    user = staff(db, make_user, ["uploads.view"], shops=[b])
    listed = user.get(BASE).json()
    assert [i["shop"]["code"] for i in listed["items"]] == ["B"]
    assert user.get(f"{BASE}/{first['id']}").status_code == 404


def test_super_admin_sees_no_items_or_tax_settings(
    admin: TestClient, db: Session, make_user
) -> None:
    shop = add_shop(db, "CH-001")
    batch = save(admin, shop, xlsx()).json()
    root = signed_in(make_user, AccessCategory.SUPER_ADMIN)
    for path in (BASE, f"{BASE}/{batch['id']}", f"{BASE}/{batch['id']}/records", SHOPS):
        assert root.get(path).status_code == 403, path
    dash = root.get("/api/v1/super-admin/dashboard")
    assert (
        dash.status_code == 200 and "Cotton Shirt" not in dash.text and "sales_tax" not in dash.text
    )
    assert db.scalar(select(User.id).where(User.email == "owner@example.test")) is not None


def test_unknown_or_tampered_expected_rate_is_refused(admin: TestClient, db: Session) -> None:
    shop = add_shop(db, "CH-001")
    for bad in ("", "abc", "-1", "101", "18.00001"):
        res = save(admin, shop, xlsx(), rate=bad)
        assert res.status_code == 409 and res.json()["error"]["code"] == "preview_mismatch", bad
    lower = save(admin, shop, xlsx(), rate="0")  # a forged lower rate
    assert lower.status_code == 409 and lower.json()["error"]["code"] == "tax_rate_changed"
    assert db.scalar(select(func.count()).select_from(UploadBatch)) == 0


def test_revision_rows_remain_append_only(admin: TestClient, db: Session) -> None:
    shop = add_shop(db, "CH-001")
    save(admin, shop, xlsx())
    with pytest.raises(Exception, match="append-only"):
        db.execute(update(UploadRevision).values(applied_sales_tax_rate=Decimal("1")))
        db.flush()
    db.rollback()
    with pytest.raises(Exception, match="append-only"):
        db.execute(update(SalesRecord).values(item="tampered"))
        db.flush()
    db.rollback()


def test_dates_in_validation_messages_stay_dd_mm_yyyy() -> None:
    other = DAY - timedelta(days=1)
    result = excel_sales.parse_workbook(xlsx([[other, *GOOD_ROW[1:]]]), DAY, Decimal("18"))
    assert other.strftime("%d/%m/%Y") in result.errors[0].message
