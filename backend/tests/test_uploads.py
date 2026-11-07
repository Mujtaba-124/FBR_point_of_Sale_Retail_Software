"""Excel Uploads (Phase 4): template, validation, authorization, integrity, concurrency."""

import io
import secrets
import threading
import zipfile
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.core.errors import AppError
from app.main import app
from app.models import (
    AccessCategory,
    AppSubscription,
    AuditEvent,
    CompanyRole,
    CompanyRolePermission,
    EmailOutbox,
    SalesRecord,
    Shop,
    UploadBatch,
    UploadRevision,
    User,
    UserShopAccess,
    UserShopAssignment,
)
from app.services import company_users, excel_sales, upload_storage
from app.services.subscription import business_today
from tests.conftest import csrf_header, login

BASE = "/api/v1/company/uploads"
ORIGIN = {"Origin": "http://localhost:3000"}
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
pytestmark = pytest.mark.usefixtures("valid_subscription")

DAY = business_today() - timedelta(days=1)
# Date, Time, Item, Customer Name, CNIC/NTN, Quantity, Rate, Amount (8-column template)
GOOD_ROW = [DAY, time(9, 30), "Cotton Shirt", "Ali Raza", "0123456-7", 2, 1000, 2000]
RATE = Decimal("18")  # the test shops' Sales Tax %


# --- Workbook builder ------------------------------------------------------------------


def xlsx(
    rows: list[list[object]] | None = None,
    *,
    headers: tuple[str, ...] | list[str] = excel_sales.HEADERS,
    sheet: str = "Sales",
    tweak=None,
) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(list(headers))
    for row in rows if rows is not None else [GOOD_ROW]:
        ws.append(row)
    cnic_column = list(headers).index("CNIC/NTN") + 1 if "CNIC/NTN" in headers else None
    for r in range(2, ws.max_row + 1):  # keep CNIC/NTN as text, like the template
        if cnic_column is None:
            break
        cell = ws.cell(row=r, column=cnic_column)
        if isinstance(cell.value, str):
            cell.data_type = "s"
    if tweak:
        tweak(ws)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def parse(
    rows: list[list[object]], sales_date: date = DAY, rate: Decimal = RATE, **kw
) -> excel_sales.ParseResult:
    return excel_sales.parse_workbook(xlsx(rows, **kw), sales_date, rate)


def codes(result: excel_sales.ParseResult) -> list[tuple[int | None, str]]:
    return [(e.row, e.code) for e in result.errors]


# --- Clients ---------------------------------------------------------------------------------


def h(client: TestClient) -> dict[str, str]:
    return {**csrf_header(client), **ORIGIN, "Content-Type": XLSX}


def signed_in(make_user, category: AccessCategory, email: str | None = None) -> TestClient:
    address, password = make_user(category, email=email)
    client = TestClient(app, base_url="https://testserver")
    assert login(client, address, password).status_code == 200
    return client


@pytest.fixture
def admin(make_user) -> TestClient:
    return signed_in(make_user, AccessCategory.COMPANY_ADMIN, "owner@example.test")


def staff(
    db: Session, make_user, permissions: list[str], *, mode: str = "selected", shops=()
) -> TestClient:
    role = CompanyRole(name=f"Role {secrets.token_hex(3)}", is_active=True, version=1)
    role.permissions = [
        CompanyRolePermission(permission=p) for p in {"dashboard.view", *permissions}
    ]
    db.add(role)
    db.commit()
    email, password = make_user(AccessCategory.COMPANY_USER)
    user = db.scalar(select(User).where(User.email == email))
    user.company_role_id = role.id  # type: ignore[union-attr]
    db.add(UserShopAccess(user_id=user.id, access_mode=mode, version=1))  # type: ignore[union-attr]
    db.flush()
    for s in shops:
        db.add(UserShopAssignment(user_id=user.id, shop_id=s.id))  # type: ignore[union-attr]
    db.commit()
    client = TestClient(app, base_url="https://testserver")
    assert login(client, email, password).status_code == 200
    client.user_id = user.id  # type: ignore[attr-defined, union-attr]
    client.role_id = role.id  # type: ignore[attr-defined]
    return client


UPLOADER = ["uploads.view", "uploads.upload", "uploads.edit_draft"]


def add_shop(db: Session, code: str, *, active: bool = True, rate: Decimal | None = RATE) -> Shop:
    shop = Shop(
        name=f"Shop {code}",
        branch_name="B",
        code=code,
        pos_id=f"P{code}",
        is_active=active,
        sales_tax_rate=rate,
    )
    db.add(shop)
    db.commit()
    return shop


def preview(
    client: TestClient,
    shop: Shop | str | None,
    data: bytes,
    day: date = DAY,
    name: str = "sales.xlsx",
):
    params = {"sales_date": day.isoformat(), "filename": name}
    if shop is not None:
        params["shop_id"] = str(shop.id) if isinstance(shop, Shop) else shop
    return client.post(f"{BASE}/preview", params=params, content=data, headers=h(client))


def save(
    client: TestClient,
    shop: Shop,
    data: bytes,
    day: date = DAY,
    checksum: str | None = None,
    name: str = "sales.xlsx",
    rate: str = "18",
):
    params = {
        "shop_id": str(shop.id),
        "sales_date": day.isoformat(),
        "filename": name,
        "expected_checksum": checksum or upload_storage.checksum(data),
        "expected_tax_rate": rate,
    }
    return client.post(BASE, params=params, content=data, headers=h(client))


def replace(
    client: TestClient,
    batch_id: str,
    data: bytes,
    revision: int,
    checksum: str | None = None,
    rate: str = "18",
):
    params = {
        "filename": "fixed.xlsx",
        "expected_checksum": checksum or upload_storage.checksum(data),
        "expected_revision": revision,
        "expected_tax_rate": rate,
    }
    return client.post(f"{BASE}/{batch_id}/replace", params=params, content=data, headers=h(client))


def twin(client: TestClient) -> TestClient:
    """Same signed-in session on an independent client (one per thread)."""
    other = TestClient(app, base_url="https://testserver")
    other.cookies.update(client.cookies)
    return other


@pytest.fixture(autouse=True)
def _empty_storage():
    """Each test starts with an empty (disposable) upload directory."""
    root = Path(get_settings().upload_storage_dir)
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        else:
            path.rmdir()
    yield


def stored_files() -> set[str]:
    root = Path(get_settings().upload_storage_dir)
    return {str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*") if p.is_file()}


def referenced_files(db: Session) -> set[str]:
    db.expire_all()
    return set(db.scalars(select(UploadRevision.storage_key)))


# --- Template ------------------------------------------------------------------------------------


def test_template_has_exactly_the_eight_columns(admin: TestClient) -> None:
    res = admin.get(f"{BASE}/template")
    assert res.status_code == 200 and res.headers["content-type"] == XLSX
    assert "attachment" in res.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(res.content))
    assert wb.sheetnames == ["Sales", "Instructions"]
    ws = wb["Sales"]
    assert tuple(ws.cell(row=1, column=c).value for c in range(1, 9)) == (
        "Date",
        "Time",
        "Item",
        "Customer Name",
        "CNIC/NTN",
        "Quantity",
        "Rate",
        "Amount",
    )
    assert ws.cell(row=1, column=9).value is None  # no tax columns any more
    assert ws.cell(row=1, column=1).fill.fgColor.rgb.endswith("0B1A3D")  # navy header
    assert ws.cell(row=2, column=1).number_format == "dd/mm/yyyy"  # a real date cell, DD/MM/YYYY
    assert ws.cell(row=2, column=2).number_format == "hh:mm"
    assert ws.cell(row=2, column=3).number_format == "@"  # Item as text
    assert ws.cell(row=2, column=5).number_format == "@"  # CNIC/NTN as text
    assert all(c.value is None for row in ws.iter_rows(min_row=2) for c in row)  # no data
    names = zipfile.ZipFile(io.BytesIO(res.content)).namelist()
    assert not any("vba" in n.lower() or "externalLink" in n for n in names)
    # The blank template itself is a valid (but empty) upload.
    with pytest.raises(AppError) as exc:
        excel_sales.parse_workbook(res.content, DAY, RATE)
    assert exc.value.code == "no_rows"
    text_lines = " ".join(str(c.value) for c in wb["Instructions"]["A"] if c.value)
    assert (
        "8 columns" in text_lines and "Sales Tax %" in text_lines and "tax exclusive" in text_lines
    )


def test_template_access(client: TestClient, make_user, db: Session) -> None:
    assert client.get(f"{BASE}/template").status_code == 401
    assert (
        signed_in(make_user, AccessCategory.SUPER_ADMIN).get(f"{BASE}/template").status_code == 403
    )
    assert (
        staff(db, make_user, ["uploads.view"], mode="none").get(f"{BASE}/template").status_code
        == 200
    )
    assert (
        staff(db, make_user, ["shops.view"], mode="none").get(f"{BASE}/template").status_code == 403
    )


# --- Validation rules ----------------------------------------------------------------------------


def test_valid_file_with_exact_decimal_totals() -> None:
    rows = [
        GOOD_ROW,  # 2000.00 -> tax 360.00, net 2360.00
        [DAY, "14:45", "Jeans", None, None, 3, "33.3333", "100.00"],  # tax 18.00
        [DAY.isoformat(), "23:59:30", "Fabric", "Walk-in", "", 1.5, 0.1, 0.15],  # 0.027 -> 0.03
    ]
    result = parse(rows)
    assert result.ok and result.total_rows == 3 and result.valid_rows == 3
    assert result.totals() == (Decimal("2100.15"), Decimal("378.03"), Decimal("2478.18"))
    assert [r.tax_amount for r in result.rows] == [
        Decimal("360.00"),
        Decimal("18.00"),
        Decimal("0.03"),
    ]
    assert all(r.tax_percent == Decimal("18.0000") for r in result.rows)  # one shop rate
    assert (
        result.rows[1].customer_name is None and result.rows[1].cnic_ntn is None
    )  # never invented
    assert result.rows[0].item == "Cotton Shirt"
    assert result.rows[2].sale_time == time(23, 59, 30)


def test_one_date_per_file_reports_the_conflicting_row() -> None:
    other = DAY - timedelta(days=1)
    result = parse([GOOD_ROW, GOOD_ROW, [other, *GOOD_ROW[1:]]])
    assert codes(result) == [(4, "date_mismatch")]
    message = result.errors[0].message
    assert "does not match the selected sales date" in message
    # User-facing dates follow the application standard, DD/MM/YYYY.
    assert other.strftime("%d/%m/%Y") in message
    assert DAY.strftime("%d/%m/%Y") in message


@pytest.mark.parametrize(
    ("value", "accepted"),
    [
        (DAY.isoformat(), True),
        (DAY.strftime("%d-%b-%Y"), True),
        (DAY.strftime("%d/%m/%Y"), False),  # ambiguous day/month order
        (DAY.strftime("%m/%d/%Y"), False),
        (datetime.combine(DAY, time(10, 0)), False),  # a date with a time
        (46000, False),  # a serial number in a General cell
        ("2026-02-30", False),
        (None, False),
    ],
)
def test_date_formats(value: object, accepted: bool) -> None:
    result = parse([[value, *GOOD_ROW[1:]]])
    assert result.ok is accepted, codes(result)


@pytest.mark.parametrize(
    ("value", "accepted"),
    [
        ("09:30", True),
        ("9:05", True),
        ("23:59", True),
        (time(14, 45), True),
        ("00:00:00", True),
        ("24:00", False),
        ("9:75", False),
        ("9:30 AM", False),
        ("930", False),
        (None, False),
        (0.5, False),
        (timedelta(hours=3), False),
    ],
)
def test_24_hour_times(value: object, accepted: bool) -> None:
    result = parse([[DAY, value, *GOOD_ROW[2:]]])
    assert result.ok is accepted, codes(result)


def test_amount_must_equal_quantity_times_rate() -> None:
    rows = [
        [DAY, "10:00", "A", None, None, 2, 1000, 2100],  # Amount != Q x R
        [DAY, "10:00", "B", None, None, 2, 1000, 2000],  # fine
    ]
    result = parse(rows)
    assert [(e.row, e.column, e.code) for e in result.errors] == [
        (2, "Amount", "calculation_mismatch")
    ]
    assert "does not equal Quantity × Rate (2,000.00)" in result.errors[0].message
    assert len(result.rows) == 1 and result.rows[0].amount == Decimal("2000")  # never altered


def test_rounding_within_one_paisa_is_accepted_and_counted() -> None:
    # 3 x 33.3333 = 99.9999 -> 100.00; the file says 99.99 (within 0.01)
    result = parse([[DAY, "10:00", "Cloth Roll", None, None, 3, "33.3333", "99.99"]])
    assert result.ok and result.rounding_differences == 1
    row = result.rows[0]
    assert row.amount == Decimal("99.99")  # stored as uploaded, not changed
    # Tax from the uploaded Amount: 99.99 x 18% = 17.9982 -> 18.00 (ROUND_HALF_UP)
    assert (row.tax_amount, row.net_amount) == (Decimal("18.00"), Decimal("117.99"))


def test_tax_is_rounded_half_up_per_row() -> None:
    # 0.25 x 18% = 0.045 -> 0.05 (half up, not banker's 0.04); 0.15 x 17.5% = 0.02625 -> 0.03
    a = parse([[DAY, "10:00", "X", None, None, 1, "0.25", "0.25"]]).rows[0]
    assert (a.tax_amount, a.net_amount) == (Decimal("0.05"), Decimal("0.30"))
    b = parse([[DAY, "10:00", "X", None, None, 1, "0.15", "0.15"]], rate=Decimal("17.5")).rows[0]
    assert (b.tax_amount, b.net_amount, b.tax_percent) == (
        Decimal("0.03"),
        Decimal("0.18"),
        Decimal("17.5000"),
    )
    zero = parse([GOOD_ROW], rate=Decimal("0")).rows[0]
    assert (zero.tax_amount, zero.net_amount) == (Decimal("0.00"), Decimal("2000"))


def test_precision_and_numeric_rules() -> None:
    rows = [
        [DAY, "10:00", "A", None, None, 1, 1, "1.005"],  # 3 decimals in money
        [DAY, "10:00", "A", None, None, 0, 1, 0],  # quantity must be > 0
        [DAY, "10:00", "A", None, None, -1, 1, 1],  # negative
        [DAY, "10:00", "A", None, None, "1,000", 1, 1000],  # thousands separator
        [DAY, "10:00", "A", None, None, 1, "1.00001", 1],  # 5 decimals in Rate
        [DAY, "10:00", "A", None, None, True, 1, 1],  # boolean
    ]
    result = parse(rows)
    assert sorted({e.row for e in result.errors}) == [2, 3, 4, 5, 6, 7]


def test_missing_required_fields() -> None:
    result = parse([[DAY, None, None, "Name only", None, None, None, None]])
    columns = {e.column for e in result.errors}
    assert columns == {"Time", "Item", "Quantity", "Rate", "Amount"}


@pytest.mark.parametrize(
    ("value", "accepted", "stored"),
    [
        ("Cotton Shirt", True, "Cotton Shirt"),
        ("  Ladies   Suit  ", True, "Ladies Suit"),  # trimmed, inner spaces collapsed
        (1205, True, "1205"),  # an item number typed as a number
        ("", False, None),
        ("   ", False, None),
        (None, False, None),
        ("=SUM(A1)", False, None),
        ("@cmd", False, None),
        ("x" * 200, True, "x" * 200),
        ("x" * 201, False, None),
        ("Bad\x7fdel", False, None),  # a control character
    ],
)
def test_item_is_required_text(value: object, accepted: bool, stored: str | None) -> None:
    result = parse([[*GOOD_ROW[:2], value, *GOOD_ROW[3:]]])
    assert result.ok is accepted, codes(result)
    if accepted:
        assert result.rows[0].item == stored
    else:
        # "=..." typed into a cell is stored as a formula: refused before the Item check.
        assert codes(result) in ([(2, "invalid_item")], [(2, "formula_not_allowed")])
        if value in (None, "", "   "):
            assert result.errors[0].message == "Item is required."


def test_cnic_is_text_and_keeps_leading_zeros() -> None:
    ok = parse([[*GOOD_ROW[:4], "0012345-6", *GOOD_ROW[5:]]])
    assert ok.ok and ok.rows[0].cnic_ntn == "0012345-6"
    numeric = parse([[*GOOD_ROW[:4], 12345, *GOOD_ROW[5:]]])
    assert codes(numeric) == [(2, "cnic_not_text")]
    bad = parse([[*GOOD_ROW[:4], "35202 1234567 1", *GOOD_ROW[5:]]])
    assert codes(bad) == [(2, "invalid_cnic")]


def test_formulas_and_formula_like_text_are_refused() -> None:
    formula = parse([[*GOOD_ROW[:7], "=F2*G2"]])
    assert codes(formula) == [(2, "formula_not_allowed")]

    def injection(ws):
        ws["D2"].value = '=HYPERLINK("http://evil")'
        ws["D2"].data_type = "s"  # stored as text, starts with '='

    text_formula = parse([GOOD_ROW], tweak=injection)
    assert codes(text_formula) == [(2, "invalid_text")]
    plus = parse([[*GOOD_ROW[:3], "+92 300 0000000", *GOOD_ROW[4:]]])
    assert codes(plus) == [(2, "invalid_text")]


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        (
            {
                "headers": (
                    "Date",
                    "Time",
                    "Product",
                    "Customer Name",
                    "CNIC/NTN",
                    "Quantity",
                    "Rate",
                    "Amount",
                )
            },
            "invalid_headers",
        ),
        ({"headers": (*excel_sales.HEADERS, "Invoice No")}, "unexpected_columns"),
        ({"headers": (*excel_sales.HEADERS, "Sale Tax %")}, "unexpected_columns"),
        ({"headers": excel_sales.LEGACY_HEADERS}, "legacy_template"),
        ({"tweak": lambda ws: ws.merge_cells("C2:D2")}, "merged_cells"),
    ],
)
def test_structure_rules(kwargs: dict, code: str) -> None:
    with pytest.raises(AppError) as exc:
        parse([GOOD_ROW], **kwargs)
    assert exc.value.code == code


def test_blank_rows_are_skipped_and_rows_are_numbered_by_excel_row() -> None:
    result = parse([GOOD_ROW, [None] * 8, [None] * 8, [DAY, "25:00", *GOOD_ROW[2:]]])
    assert result.total_rows == 2 and codes(result) == [(5, "invalid_time")]


def _zip_with(extra: dict[str, bytes]) -> bytes:
    base = io.BytesIO(xlsx())
    out = io.BytesIO()
    with zipfile.ZipFile(base) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            dst.writestr(item, src.read(item.filename))
        for name, data in extra.items():
            dst.writestr(name, data)
    return out.getvalue()


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", "file_empty"),
        (b"not an excel file at all", "not_xlsx"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64, "file_protected_or_legacy"),
        (xlsx()[:300], "corrupt_file"),
        (_zip_with({"xl/vbaProject.bin": b"macro"}), "macros_not_allowed"),
        (_zip_with({"xl/externalLinks/externalLink1.xml": b"<x/>"}), "external_links_not_allowed"),
    ],
)
def test_malformed_and_malicious_files_are_rejected(data: bytes, code: str) -> None:
    with pytest.raises(AppError) as exc:
        excel_sales.parse_workbook(data, DAY, RATE)
    assert exc.value.code == code


def test_row_and_size_limits(monkeypatch, admin: TestClient, db: Session) -> None:
    monkeypatch.setattr(get_settings(), "upload_max_rows", 3)
    with pytest.raises(AppError) as exc:
        parse([GOOD_ROW] * 4)
    assert exc.value.code == "too_many_rows"
    shop = add_shop(db, "S1")
    monkeypatch.setattr(get_settings(), "upload_max_bytes", 1000)
    res = preview(admin, shop, xlsx())
    assert res.status_code == 413 and res.json()["error"]["code"] == "file_too_large"


# --- Upload flow (Company Admin) ------------------------------------------------------------------


def test_admin_previews_saves_lists_and_views(admin: TestClient, db: Session) -> None:
    shop = add_shop(db, "CH-001")
    data = xlsx([GOOD_ROW, [DAY, "11:00", "Jeans", "Sara", "35202-1234567-1", 1, "99.99", "99.99"]])
    pre = preview(admin, shop, data)
    assert pre.status_code == 200, pre.text
    body = pre.json()
    assert body["can_save"] is True and body["total_rows"] == 2 and body["error_count"] == 0
    # 2000.00 + 99.99; tax 360.00 + 18.00 (17.9982 rounded); net 2360.00 + 117.99
    assert body["totals"] == {"amount": "2099.99", "sales_tax": "378.00", "net_amount": "2477.99"}
    assert body["applied_sales_tax_rate"] == "18.00" and body["tax_rate_source"] == "shop"
    assert body["rows"][1]["item"] == "Jeans"
    assert body["rows"][1]["cnic_ntn"] == "•••••-••••567-1"  # masked: last 4 characters only
    assert body["shop"]["code"] == "CH-001" and body["checksum"] == upload_storage.checksum(data)
    assert db.scalar(select(func.count()).select_from(UploadBatch)) == 0  # preview saved nothing

    res = save(admin, shop, data)
    assert res.status_code == 201, res.text
    batch = res.json()
    assert (
        batch["status"] == "draft"
        and batch["current_revision"] == 1
        and batch["total_records"] == 2
    )
    assert batch["totals"]["net_amount"] == "2477.99" and batch["can_replace"] is True
    assert (
        batch["applied_sales_tax_rate"] == "18.0000" and batch["template_format"] == "standard_8col"
    )

    listed = admin.get(BASE).json()
    assert listed["total"] == 1 and listed["items"][0]["filename"] == "sales.xlsx"
    detail = admin.get(f"{BASE}/{batch['id']}").json()
    assert [r["revision_number"] for r in detail["revisions"]] == [1]
    records = admin.get(f"{BASE}/{batch['id']}/records", params={"limit": 1}).json()
    assert (
        records["total"] == 2
        and len(records["items"]) == 1
        and records["items"][0]["excel_row"] == 2
    )
    original = admin.get(f"{BASE}/{batch['id']}/revisions/1/original")
    assert original.status_code == 200 and original.content == data
    assert "attachment" in original.headers["content-disposition"]
    row = db.scalar(select(SalesRecord).where(SalesRecord.excel_row == 3))
    assert row is not None and row.cnic_ntn == "35202-1234567-1" and row.amount == Decimal("99.99")


def test_preview_needs_a_specific_shop_and_a_valid_past_date(
    admin: TestClient, db: Session
) -> None:
    shop = add_shop(db, "S1")
    assert preview(admin, None, xlsx()).json()["error"]["code"] == "shop_required"
    assert preview(admin, "all", xlsx()).json()["error"]["code"] == "shop_required"
    future = business_today() + timedelta(days=1)
    assert preview(admin, shop, xlsx(), day=future).json()["error"]["code"] == "invalid_sales_date"
    assert preview(admin, shop, xlsx(), name="sales.csv").json()["error"]["code"] == "not_xlsx"


def test_preview_lists_row_errors_and_save_refuses_them(admin: TestClient, db: Session) -> None:
    shop = add_shop(db, "S1")
    bad = xlsx([GOOD_ROW, [DAY, "25:00", *GOOD_ROW[2:]], [DAY - timedelta(days=1), *GOOD_ROW[1:]]])
    body = preview(admin, shop, bad).json()
    assert body["can_save"] is False and body["invalid_rows"] == 2 and body["valid_rows"] == 1
    assert [(e["row"], e["column"]) for e in body["errors"]] == [(3, "Time"), (4, "Date")]
    res = save(admin, shop, bad)
    assert res.status_code == 422 and res.json()["error"]["code"] == "upload_invalid"
    assert db.scalar(select(func.count()).select_from(UploadBatch)) == 0
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "upload.rejected"))
    assert event is not None and event.details["invalid_rows"] == 2


# --- Authorization ---------------------------------------------------------------


def test_company_user_uploads_only_to_assigned_shops(db: Session, make_user) -> None:
    ch1, ch2 = add_shop(db, "CH-001"), add_shop(db, "CH-002")
    user = staff(db, make_user, UPLOADER, shops=[ch1])
    assert save(user, ch1, xlsx()).status_code == 201
    denied = save(user, ch2, xlsx())
    assert denied.status_code == 404 and denied.json()["error"]["code"] == "shop_not_found"
    assert preview(user, ch2, xlsx()).status_code == 404


def test_shop_assignment_without_module_permission_is_denied(db: Session, make_user) -> None:
    ch1 = add_shop(db, "CH-001")
    viewer = staff(db, make_user, ["uploads.view"], shops=[ch1])
    assert save(viewer, ch1, xlsx()).status_code == 403
    nobody = staff(db, make_user, [], mode="all")
    assert nobody.get(BASE).status_code == 403


def test_no_shop_access_cannot_upload_or_see_uploads(
    admin: TestClient, db: Session, make_user
) -> None:
    ch1 = add_shop(db, "CH-001")
    assert save(admin, ch1, xlsx()).status_code == 201
    user = staff(db, make_user, UPLOADER, mode="none")
    assert (
        save(user, ch1, xlsx(), day=DAY - timedelta(days=1)).json()["error"]["code"]
        == "shop_not_found"
    )
    assert user.get(BASE).json()["total"] == 0


def test_all_assigned_shops_never_includes_other_shops(
    admin: TestClient, db: Session, make_user
) -> None:
    shops = [add_shop(db, f"S{i}") for i in range(3)]
    for s in shops:
        assert save(admin, s, xlsx()).status_code == 201
    user = staff(db, make_user, ["uploads.view"], shops=shops[:2])
    listed = user.get(BASE).json()
    assert sorted(i["shop"]["code"] for i in listed["items"]) == ["S0", "S1"]
    assert user.get(BASE, params={"shop": str(shops[2].id)}).status_code == 404
    other = admin.get(BASE, params={"shop": str(shops[2].id)}).json()["items"][0]["id"]
    for path in (
        f"{BASE}/{other}",
        f"{BASE}/{other}/records",
        f"{BASE}/{other}/revisions/1/original",
    ):
        assert user.get(path).status_code == 404  # cross-shop detail/download denied
    assert admin.get(BASE).json()["total"] == 3


def test_inactive_shop_rejects_new_uploads_but_keeps_history(
    admin: TestClient, db: Session
) -> None:
    shop = add_shop(db, "S1")
    batch = save(admin, shop, xlsx()).json()
    db.execute(update(Shop).where(Shop.id == shop.id).values(is_active=False))
    db.commit()
    res = save(admin, shop, xlsx(), day=DAY - timedelta(days=1))
    assert res.status_code == 409 and res.json()["error"]["code"] == "shop_inactive"
    assert replace(admin, batch["id"], xlsx(), 1).json()["error"]["code"] == "shop_inactive"
    assert admin.get(f"{BASE}/{batch['id']}").status_code == 200  # history stays readable
    assert admin.get(BASE, params={"shop": str(shop.id)}).json()["total"] == 1


def test_expired_subscription_and_super_admin_are_denied(
    admin: TestClient, db: Session, make_user
) -> None:
    shop = add_shop(db, "S1")
    root = signed_in(make_user, AccessCategory.SUPER_ADMIN)
    for res in (root.get(BASE), root.get(f"{BASE}/template"), preview(root, shop, xlsx())):
        assert res.status_code == 403
    today = clock.utcnow().date()
    db.execute(
        update(AppSubscription).values(
            start_date=today - timedelta(days=400), expiry_date=today - timedelta(days=1)
        )
    )
    db.commit()
    for res in (admin.get(BASE), save(admin, shop, xlsx())):
        assert res.status_code == 403 and res.json()["error"]["code"] == "subscription_expired"


def test_unauthenticated_csrf_and_foreign_origin(
    client: TestClient, admin: TestClient, db: Session
) -> None:
    shop = add_shop(db, "S1")
    assert client.get(BASE).status_code == 401
    params = {"shop_id": str(shop.id), "sales_date": DAY.isoformat(), "filename": "a.xlsx"}
    no_csrf = admin.post(
        f"{BASE}/preview", params=params, content=xlsx(), headers={**ORIGIN, "Content-Type": XLSX}
    )
    assert no_csrf.status_code == 403 and no_csrf.json()["error"]["code"] == "csrf_failed"
    foreign = admin.post(
        f"{BASE}/preview",
        params=params,
        content=xlsx(),
        headers={**csrf_header(admin), "Origin": "https://evil.test"},
    )
    assert foreign.status_code == 403


# --- Unique Shop + Date, replacement, integrity -----------------------------------


def test_one_current_upload_per_shop_and_date(admin: TestClient, db: Session) -> None:
    a, b = add_shop(db, "A"), add_shop(db, "B")
    assert save(admin, a, xlsx()).status_code == 201
    dup = save(admin, a, xlsx())
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "upload_exists"
    assert save(admin, b, xlsx()).status_code == 201  # another shop, same date
    other_day = DAY - timedelta(days=1)
    assert save(admin, a, xlsx([[other_day, *GOOD_ROW[1:]]]), day=other_day).status_code == 201
    existing = preview(admin, a, xlsx()).json()["existing"]
    assert existing["status"] == "draft" and existing["can_replace"] is True


def test_simultaneous_uploads_create_one_batch_and_leak_no_files(
    admin: TestClient, db: Session
) -> None:
    shop = add_shop(db, "S1")
    data = xlsx()
    barrier = threading.Barrier(4)
    results: list[int] = []

    clients = [twin(admin) for _ in range(4)]
    shop = SimpleNamespace(id=shop.id)  # plain value: threads must not touch the test session

    def worker(c: TestClient) -> None:
        barrier.wait()
        results.append(save(c, shop, data).status_code)

    threads = [threading.Thread(target=worker, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(results) == [201, 409, 409, 409]
    assert db.scalar(select(func.count()).select_from(UploadBatch)) == 1
    assert stored_files() >= referenced_files(db)
    assert len(stored_files() - referenced_files(db)) == 0  # losers' files were discarded


def test_replacement_adds_a_revision_and_keeps_history(admin: TestClient, db: Session) -> None:
    shop = add_shop(db, "S1")
    first = xlsx()
    batch = save(admin, shop, first).json()
    second = xlsx([GOOD_ROW, GOOD_ROW])
    res = replace(admin, batch["id"], second, 1)
    assert res.status_code == 200, res.text
    assert res.json()["current_revision"] == 2 and res.json()["total_records"] == 2
    detail = admin.get(f"{BASE}/{batch['id']}").json()
    assert [(r["revision_number"], r["is_current"]) for r in detail["revisions"]] == [
        (2, True),
        (1, False),
    ]
    assert admin.get(f"{BASE}/{batch['id']}/records", params={"revision": 1}).json()["total"] == 1
    assert admin.get(f"{BASE}/{batch['id']}/revisions/1/original").content == first
    assert admin.get(f"{BASE}/{batch['id']}/revisions/2/original").content == second
    with pytest.raises(Exception, match="append-only"):
        db.execute(update(SalesRecord).values(customer_name="tampered"))
        db.flush()
    db.rollback()
    with pytest.raises(Exception, match="append-only"):
        db.execute(text("DELETE FROM upload_revisions"))
    db.rollback()
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "upload.replaced"))
    assert event is not None and (
        event.details["previous_revision"],
        event.details["revision"],
    ) == (1, 2)


def test_invalid_replacement_leaves_the_draft_intact(admin: TestClient, db: Session) -> None:
    shop = add_shop(db, "S1")
    batch = save(admin, shop, xlsx()).json()
    files_before = stored_files()
    bad = xlsx([[DAY, "99:99", *GOOD_ROW[2:]]])
    res = replace(admin, batch["id"], bad, 1)
    assert res.status_code == 422
    other_date = xlsx([[DAY - timedelta(days=1), *GOOD_ROW[1:]]])
    assert replace(admin, batch["id"], other_date, 1).status_code == 422  # must keep shop + date
    after = admin.get(f"{BASE}/{batch['id']}").json()
    assert after["batch"]["current_revision"] == 1 and len(after["revisions"]) == 1
    assert stored_files() == files_before


def test_concurrent_replacements_do_not_lose_updates(admin: TestClient, db: Session) -> None:
    shop = add_shop(db, "S1")
    batch = save(admin, shop, xlsx()).json()
    files = [xlsx([GOOD_ROW] * n) for n in (2, 3, 4)]
    barrier = threading.Barrier(3)
    results: list[int] = []

    def worker(c: TestClient, data: bytes) -> None:
        barrier.wait()
        results.append(replace(c, batch["id"], data, 1).status_code)

    threads = [threading.Thread(target=worker, args=(twin(admin), f)) for f in files]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(results) == [200, 409, 409]
    detail = admin.get(f"{BASE}/{batch['id']}").json()
    assert detail["batch"]["current_revision"] == 2 and len(detail["revisions"]) == 2
    assert stored_files() == referenced_files(db)


def test_replacement_is_refused_once_the_workflow_has_started(
    admin: TestClient, db: Session
) -> None:
    shop = add_shop(db, "S1")
    batch = save(admin, shop, xlsx()).json()
    db.execute(update(UploadBatch).values(status="wait_for_approval"))
    db.commit()
    res = replace(admin, batch["id"], xlsx([GOOD_ROW, GOOD_ROW]), 1)
    assert res.status_code == 409 and res.json()["error"]["code"] == "upload_not_draft"
    assert admin.get(f"{BASE}/{batch['id']}").json()["batch"]["can_replace"] is False


def test_preview_substitution_and_stale_revision(admin: TestClient, db: Session) -> None:
    shop = add_shop(db, "S1")
    checked = xlsx()
    other = xlsx([GOOD_ROW, GOOD_ROW])
    res = save(admin, shop, other, checksum=upload_storage.checksum(checked))
    assert res.status_code == 409 and res.json()["error"]["code"] == "preview_mismatch"
    batch = save(admin, shop, checked).json()
    assert replace(admin, batch["id"], other, 1).status_code == 200
    stale = replace(admin, batch["id"], xlsx([GOOD_ROW] * 3), 1)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_upload"


def test_changes_between_preview_and_save_are_caught(
    admin: TestClient, db: Session, make_user
) -> None:
    a, b = add_shop(db, "A"), add_shop(db, "B")
    user = staff(db, make_user, UPLOADER, shops=[a, b])
    data = xlsx()
    assert preview(user, a, data).json()["can_save"] is True
    db.execute(UserShopAssignment.__table__.delete().where(UserShopAssignment.shop_id == a.id))
    db.commit()
    assert save(user, a, data).json()["error"]["code"] == "shop_not_found"  # revoked
    assert preview(user, b, data).status_code == 200
    db.execute(update(Shop).where(Shop.id == b.id).values(is_active=False))
    db.commit()
    assert save(user, b, data).json()["error"]["code"] == "shop_inactive"  # deactivated
    db.execute(update(Shop).where(Shop.id == b.id).values(is_active=True))
    today = clock.utcnow().date()
    db.execute(
        update(AppSubscription).values(
            start_date=today - timedelta(days=400), expiry_date=today - timedelta(days=1)
        )
    )
    db.commit()
    assert save(user, b, data).json()["error"]["code"] == "subscription_expired"  # expired
    assert db.scalar(select(func.count()).select_from(UploadBatch)) == 0
    assert stored_files() == referenced_files(db)  # no leftovers


def test_original_download_needs_view_permission(db: Session, make_user, admin: TestClient) -> None:
    shop = add_shop(db, "S1")
    batch = save(admin, shop, xlsx()).json()
    no_perm = staff(db, make_user, ["shops.view"], shops=[shop])
    assert no_perm.get(f"{BASE}/{batch['id']}/revisions/1/original").status_code == 403
    viewer = staff(db, make_user, ["uploads.view"], shops=[shop])
    assert viewer.get(f"{BASE}/{batch['id']}/revisions/1/original").status_code == 200
    assert admin.get(f"{BASE}/{batch['id']}/revisions/9/original").status_code == 404


def test_tampered_original_fails_its_integrity_check(admin: TestClient, db: Session) -> None:
    shop = add_shop(db, "S1")
    batch = save(admin, shop, xlsx()).json()
    key = db.scalar(select(UploadRevision.storage_key))
    (Path(get_settings().upload_storage_dir) / key).write_bytes(b"tampered")  # type: ignore[operator]
    res = admin.get(f"{BASE}/{batch['id']}/revisions/1/original")
    assert res.status_code == 500 and res.json()["error"]["code"] == "original_file_corrupt"


# --- Dashboard, audit, unrelated limits ---------------------------------------------------------


def test_dashboard_sales_follow_the_shop_context(admin: TestClient, db: Session) -> None:
    a, b = add_shop(db, "A"), add_shop(db, "B")
    save(admin, a, xlsx())
    save(admin, b, xlsx([GOOD_ROW, GOOD_ROW]))
    url = "/api/v1/company/dashboard/summary"
    everything = admin.get(url).json()
    assert (
        everything["sales_overview"]["uploads"] == 2
        and everything["sales_overview"]["records"] == 3
    )
    assert everything["sales_overview"]["total_net_amount"] == "7080.00"  # 3 x 2,360.00
    assert "Draft" in everything["sales_overview"]["status_note"]
    one = admin.get(url, params={"shop_id": str(b.id)}).json()
    assert one["sales_overview"]["records"] == 2
    assert [r["shop_code"] for r in one["recent_uploads"]["items"]] == ["B"]
    assert everything["metrics"]["pending_approvals"]["available"] is False  # still honest


def test_audit_never_holds_customer_data(admin: TestClient, db: Session) -> None:
    shop = add_shop(db, "S1")
    data = xlsx(
        [[DAY, "10:00", "Secret Item", "Private Customer Name", "0099887-1", 2, 1000, 2000]]
    )
    batch = save(admin, shop, data).json()
    replace(admin, batch["id"], data, 1)
    admin.get(f"{BASE}/{batch['id']}/revisions/1/original")
    save(
        admin,
        shop,
        xlsx([[DAY, "77:00", "Secret Item", "Private Customer Name", "0099887-1", *GOOD_ROW[5:]]]),
        day=DAY,
    )
    dump = " ".join(str(d) for d in db.scalars(select(AuditEvent.details)))
    for needle in ("Private Customer Name", "0099887-1", "sales.xlsx", "Secret Item"):
        assert needle not in dump
    actions = set(db.scalars(select(AuditEvent.action).where(AuditEvent.action.like("upload.%"))))
    assert {"upload.created", "upload.replaced", "upload.original_downloaded"} <= actions


def test_no_email_or_external_calls_and_limits_unchanged(admin: TestClient, db: Session) -> None:
    shop = add_shop(db, "S1")
    save(admin, shop, xlsx())
    assert db.scalar(select(func.count()).select_from(EmailOutbox)) == 0
    assert company_users.MAX_ACTIVE_COMPANY_ACCOUNTS == 15


def test_an_uploader_cannot_be_deleted_away_from_history(admin: TestClient, db: Session) -> None:
    """Revisions are immutable: deleting their uploader is refused outright (RESTRICT)."""
    shop = add_shop(db, "S1")
    assert save(admin, shop, xlsx()).status_code == 201
    owner_id = db.scalar(select(User.id).where(User.email == "owner@example.test"))
    db.execute(text("DELETE FROM authentication_sessions"))
    db.commit()
    with pytest.raises(Exception, match="upload_revisions_uploaded_by_user_id_fkey"):
        db.execute(text("DELETE FROM users WHERE id = :u"), {"u": owner_id})
    db.rollback()
    assert db.scalar(select(UploadRevision.uploaded_by_user_id)) == owner_id


def test_decimals_are_returned_in_plain_notation(admin: TestClient, db: Session) -> None:
    """Whole numbers such as 1000 must never come back as 1E+3."""
    shop = add_shop(db, "S1")
    data = xlsx([[DAY, "10:00", "Shirt", None, None, 2, 1000, 2000]])
    body = preview(admin, shop, data).json()
    row = body["rows"][0]
    assert (row["rate"], row["amount"], row["tax_amount"], row["net_amount"]) == (
        "1000",
        "2000",
        "360.00",
        "2360.00",
    )
    saved = save(admin, shop, data).json()
    assert saved["totals"] == {"amount": "2000.00", "sales_tax": "360.00", "net_amount": "2360.00"}
    records = admin.get(f"{BASE}/{saved['id']}/records").json()["items"][0]
    assert records["rate"] == "1000.0000" and records["amount"] == "2000.00"
    dash = admin.get("/api/v1/company/dashboard/summary").json()["sales_overview"]
    assert dash["total_net_amount"] == "2360.00"
    for dumped in (str(body), str(saved), str(records), str(dash)):
        assert "E+" not in dumped
