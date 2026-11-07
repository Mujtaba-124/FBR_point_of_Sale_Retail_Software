"""Excel sales template and file validation (pure functions, no database).

Columns (fixed, client-approved in Phase 4.2, in this order):
    Date | Time | Item | Customer Name | CNIC/NTN | Quantity | Rate | Amount

Tax is not part of the file. It is TAX EXCLUSIVE and comes from the shop
(the caller passes the rate to apply; see app.services.uploads):
      Amount          = Quantity x Rate            (uploaded; validated)
      Sales Tax Amount = Amount x Sales Tax % / 100 (calculated, ROUND_HALF_UP, 2 places)
      Net Amount       = Amount + Sales Tax Amount  (calculated)
Tax is rounded per row; file totals are the sums of the rounded rows.

The previous 10-column layout (... Amount | Sale Tax % | Sale Tax Amount |
Net Amount) is recognised and refused with a clear message: it is never
reinterpreted as the new format. Saved 10-column revisions stay viewable.

Import contract (documented in the template's Instructions):
- One sales date per file: every row's Date must equal the selected Sales Date.
- Date: an Excel date cell, or text YYYY-MM-DD / DD-Mon-YYYY (07-Nov-2026).
  Text such as 07/11/2026 is rejected: day/month order would be ambiguous.
  Plain numbers (date serials in a General cell) are rejected.
- Time: 24-hour. An Excel time cell, or text H:MM / HH:MM[:SS] (00:00-23:59).
- Item: required text (the sold item or description), trimmed, at most 200
  characters, never starting with = + - @.
- Customer Name, CNIC/NTN: optional (no rule in the requirements makes them
  mandatory); never invented when blank. CNIC/NTN must be a text cell so
  leading zeros survive; letters, digits and hyphens, at most 20.
- Quantity > 0 (max 3 decimals); Rate >= 0 (max 4 decimals); Amount >= 0
  (max 2 decimals).
- Amount is checked against Quantity x Rate rounded ROUND_HALF_UP to 2 places
  with a tolerance of 0.01 (one paisa): within it is accepted and counted as a
  rounding difference; beyond it is a row error. The uploaded Amount is stored
  exactly as given (never "corrected"); tax and net are calculated from it.
- No formulas, macros, external links, merged cells or extra columns.
Any row error blocks the whole file (nothing is saved).
"""

import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.core.config import get_settings
from app.core.dates import display_date
from app.core.errors import AppError

HEADERS = (
    "Date",
    "Time",
    "Item",
    "Customer Name",
    "CNIC/NTN",
    "Quantity",
    "Rate",
    "Amount",
)
# The previous template (before Phase 4.2). Recognised only to refuse it clearly.
LEGACY_HEADERS = (
    "Date",
    "Time",
    "Customer Name",
    "CNIC/NTN",
    "Quantity",
    "Rate",
    "Amount",
    "Sale Tax %",
    "Sale Tax Amount",
    "Net Amount",
)
DATA_SHEET = "Sales"
CENT = Decimal("0.01")
TOLERANCE = Decimal("0.01")
MAX_MONEY = Decimal("999999999999.99")
MAX_ERRORS_RETURNED = 500
NAME_MAX = 120
ITEM_MAX = 200
RATE_PLACES = Decimal("0.0001")
CNIC_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z-]{0,19}$")
NUMBER_RE = re.compile(r"^\d+(\.\d+)?$")
TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MON_DATE_RE = re.compile(r"^(\d{1,2})[- ]([A-Za-z]{3})[- ](\d{4})$")
MONTHS = {
    m: i
    for i, m in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1
    )
}
EXCEL_EPOCHS = {date(1899, 12, 30), date(1899, 12, 31), date(1900, 1, 1)}
FORMULA_PREFIXES = ("=", "+", "-", "@")


# --- Template ----------------------------------------------------------------------


def build_template() -> bytes:
    """A blank .xlsx: 'Sales' (headers + formatted empty rows) and 'Instructions'."""
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = DATA_SHEET
    header_fill = PatternFill("solid", fgColor="0B1A3D")
    widths = (14, 10, 32, 28, 20, 12, 14, 16)
    formats = (
        "dd/mm/yyyy",  # a real date cell, shown day first
        "hh:mm",  # 24-hour
        "@",  # Item: text
        "@",  # Customer Name: text
        "@",  # CNIC/NTN: text, keeps leading zeros
        "#,##0.###",
        "#,##0.00##",
        "#,##0.00",
    )
    for col, (title, width) in enumerate(zip(HEADERS, widths, strict=True), 1):
        cell = ws.cell(row=1, column=col, value=title)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[get_column_letter(col)].width = width
    for row in range(2, 202):  # optional blank input rows, pre-formatted
        for col, fmt in enumerate(formats, 1):
            ws.cell(row=row, column=col).number_format = fmt
    ws.freeze_panes = "A2"

    info = wb.create_sheet("Instructions")
    info.column_dimensions["A"].width = 110
    lines = [
        "Cheena FBR POS Software - Sales upload template (8 columns)",
        "",
        "One file = one shop and one sales date. Enter rows on the 'Sales' sheet only;",
        "keep the header row exactly as it is and do not add columns.",
        "Columns: Date, Time, Item, Customer Name, CNIC/NTN, Quantity, Rate, Amount.",
        "",
        "Date: the same sales date on every row, as an Excel date cell. The Date column shows",
        "  dates as DD/MM/YYYY (07/11/2026 = 7 November 2026). Excel reads what you type using",
        "  the computer's region settings, so after typing check that the cell shows the day and",
        "  month you meant. Text dates are accepted only as 2026-11-07 or 07-Nov-2026; text such",
        "  as 07/11/2026 is not accepted because it can mean 7 November or 11 July.",
        "Time: 24-hour format, for example 09:30 or 14:45 (00:00 to 23:59).",
        "Item: required, the item sold or its description (for example Cotton Shirt).",
        "Customer Name: optional. CNIC/NTN: optional; keep it as text so leading zeros stay.",
        "Quantity: more than 0 (up to 3 decimals). Rate: 0 or more (up to 4 decimals).",
        "Amount = Quantity x Rate, at most 2 decimals; a difference of up to 0.01 is accepted",
        "  as rounding. Amount is the price before sales tax.",
        "",
        "Sales tax is NOT entered in this file. The software calculates it from the Sales",
        "Tax % set for the shop in Shop Management (tax exclusive):",
        "  Sales Tax Amount = Amount x Sales Tax % / 100 (rounded to 2 decimals per row)",
        "  Net Amount = Amount + Sales Tax Amount",
        "The applied rate is shown when the file is checked and is saved with the upload.",
        "Replacing a Draft keeps the rate that Draft was saved with.",
        "",
        "Type values in: formulas, macros and links to other files are not accepted.",
    ]
    for i, line in enumerate(lines, 1):
        info.cell(row=i, column=1, value=line)
    info["A1"].font = Font(bold=True, size=13)

    wb.properties.creator = "Cheena FBR POS Software"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# --- Results ----------------------------------------------------------------------------


@dataclass(frozen=True)
class RowError:
    row: int | None  # Excel row number; None for file-level problems
    column: str | None
    code: str
    message: str


@dataclass
class ParsedRow:
    excel_row: int
    sale_date: date
    sale_time: time
    item: str
    customer_name: str | None
    cnic_ntn: str | None
    quantity: Decimal
    rate: Decimal
    amount: Decimal
    tax_percent: Decimal
    tax_amount: Decimal
    net_amount: Decimal


@dataclass
class ParseResult:
    rows: list[ParsedRow] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    error_count: int = 0
    total_rows: int = 0
    invalid_rows: set[int] = field(default_factory=set)
    rounding_differences: int = 0

    @property
    def valid_rows(self) -> int:
        return self.total_rows - len(self.invalid_rows)

    @property
    def ok(self) -> bool:
        return self.error_count == 0 and self.total_rows > 0

    def add(self, row: int | None, column: str | None, code: str, message: str) -> None:
        self.error_count += 1
        if row is not None:
            self.invalid_rows.add(row)
        if len(self.errors) < MAX_ERRORS_RETURNED:
            self.errors.append(RowError(row, column, code, message))

    def totals(self) -> tuple[Decimal, Decimal, Decimal]:
        amount = sum((r.amount for r in self.rows), Decimal("0"))
        tax = sum((r.tax_amount for r in self.rows), Decimal("0"))
        net = sum((r.net_amount for r in self.rows), Decimal("0"))
        return amount, tax, net


def file_error(code: str, message: str, status: int = 422) -> AppError:
    return AppError(status, code, message)


# --- Container checks (before any XML is parsed) ----------------------------------------


def inspect_container(data: bytes) -> None:
    settings = get_settings()
    if not data:
        raise file_error("file_empty", "The file is empty.")
    if len(data) > settings.upload_max_bytes:
        limit = settings.upload_max_bytes // (1024 * 1024)
        raise file_error("file_too_large", f"The file is larger than {limit} MB.", 413)
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise file_error(
            "file_protected_or_legacy",
            "This file is password-protected or in the old .xls format. Save it as an "
            "unprotected .xlsx workbook and try again.",
        )
    if data[:4] != b"PK\x03\x04":
        raise file_error("not_xlsx", "The file is not an Excel .xlsx workbook.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            names = {e.filename for e in entries}
    except zipfile.BadZipFile:
        raise file_error("corrupt_file", "The file is damaged and cannot be read.") from None
    if len(entries) > settings.upload_max_zip_entries:
        raise file_error("corrupt_file", "The workbook has an unexpected structure.")
    total = 0
    for entry in entries:
        if entry.flag_bits & 0x1:
            raise file_error("file_protected_or_legacy", "Encrypted workbooks are not accepted.")
        total += entry.file_size
        if (
            entry.compress_size
            and entry.file_size > 1_000_000
            and (entry.file_size / entry.compress_size > 200)
        ):
            raise file_error("corrupt_file", "The workbook is compressed suspiciously.")
    if total > settings.upload_max_uncompressed_bytes:
        raise file_error("file_too_large", "The workbook is too large when unpacked.", 413)
    if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
        raise file_error("not_xlsx", "The file is not an Excel .xlsx workbook.")
    if any(n.lower().endswith("vbaproject.bin") for n in names):
        raise file_error("macros_not_allowed", "Workbooks with macros are not accepted.")
    if any(n.startswith("xl/externalLinks/") for n in names):
        raise file_error(
            "external_links_not_allowed",
            "The workbook links to other files. Remove the links and type the values in.",
        )


# --- Cell parsing --------------------------------------------------------------------------


def _text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _parse_date(value: object) -> tuple[date | None, str | None]:
    if isinstance(value, datetime):
        if value.time() != time(0, 0):
            return None, "Date must be a date only, without a time."
        return value.date(), None
    if isinstance(value, date):
        return value, None
    if isinstance(value, bool) or isinstance(value, int | float):
        return None, "Date is a plain number. Format the cell as a date (e.g. 07-Nov-2026)."
    text = _text(value)
    if text is None:
        return None, "Date is missing."
    try:
        if ISO_DATE_RE.match(text):
            return date.fromisoformat(text), None
        match = MON_DATE_RE.match(text)
        if match and match.group(2).lower() in MONTHS:
            return date(
                int(match.group(3)), MONTHS[match.group(2).lower()], int(match.group(1))
            ), None
    except ValueError:
        return None, f"Date '{text}' is not a real calendar date."
    return None, f"Date '{text}' is not in a supported format (2026-11-07 or 07-Nov-2026)."


def _parse_time(value: object) -> tuple[time | None, str | None]:
    if isinstance(value, time):
        return value.replace(microsecond=0), None
    if isinstance(value, datetime):
        if value.date() in EXCEL_EPOCHS:
            return value.time().replace(microsecond=0), None
        return None, "Time contains a date. Enter the time only, e.g. 14:45."
    if isinstance(value, timedelta):
        return None, "Time is a duration, not a time of day. Use 24-hour time, e.g. 14:45."
    if isinstance(value, bool) or isinstance(value, int | float):
        return None, "Time is a plain number. Enter 24-hour time, e.g. 14:45."
    text = _text(value)
    if text is None:
        return None, "Time is missing."
    match = TIME_RE.match(text)
    if not match:
        return None, f"Time '{text}' is not a valid 24-hour time (00:00 to 23:59)."
    return time(int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)), None


def _decimal(value: object) -> tuple[Decimal | None, str | None]:
    if isinstance(value, bool):
        return None, "is not a number"
    if isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, float):
        number = Decimal(str(value))  # shortest repr: 0.1 -> Decimal("0.1"), not binary noise
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None, "is missing"
        if not NUMBER_RE.match(text):
            return None, f"'{text}' is not a plain number (digits and one decimal point only)"
        try:
            number = Decimal(text)
        except InvalidOperation:
            return None, "is not a number"
    elif value is None:
        return None, "is missing"
    else:
        return None, "is not a number"
    if not number.is_finite():
        return None, "is not a number"
    if number < 0:
        return None, "must not be negative"
    return number, None  # as written: never exponent form (normalize() would give 1E+3)


def _places(number: Decimal) -> int:
    exponent = number.normalize().as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


def _money(n: Decimal) -> str:
    return f"{n:,.2f}"


# --- Workbook validation -------------------------------------------------------------------


def parse_workbook(data: bytes, sales_date: date, tax_rate: Decimal) -> ParseResult:
    """Validate a sales workbook for one shop and ``sales_date`` (see module docstring),
    calculating tax and net amount with ``tax_rate`` (a percentage, 0-100).

    Raises AppError for file-level problems; row problems are collected.
    """
    if not (Decimal("0") <= tax_rate <= Decimal("100")):
        raise ValueError("tax_rate must be a percentage from 0 to 100")
    inspect_container(data)
    try:
        wb = load_workbook(
            io.BytesIO(data), read_only=False, data_only=False, keep_vba=False, keep_links=False
        )
    except Exception:  # openpyxl raises many types for damaged packages
        raise file_error("corrupt_file", "The file is damaged and cannot be read.") from None
    ws = wb[DATA_SHEET] if DATA_SHEET in wb.sheetnames else wb.worksheets[0]

    found = [_text(ws.cell(row=1, column=c).value) for c in range(1, len(LEGACY_HEADERS) + 1)]
    lowered = [(h or "").lower() for h in found]
    if lowered == [h.lower() for h in LEGACY_HEADERS]:
        raise file_error(
            "legacy_template",
            "This file uses the previous 10-column template (with Sale Tax %, Sale Tax Amount "
            "and Net Amount). Download the new 8-column template: sales tax is now calculated "
            "from the shop's Sales Tax %.",
        )
    if lowered[: len(HEADERS)] != [h.lower() for h in HEADERS]:
        raise file_error(
            "invalid_headers",
            "The header row does not match the template. Expected: " + ", ".join(HEADERS) + ".",
        )
    max_col = ws.max_column or len(HEADERS)
    if max_col > len(HEADERS) and any(
        ws.cell(row=1, column=c).value not in (None, "")
        for c in range(len(HEADERS) + 1, max_col + 1)
    ):
        raise file_error("unexpected_columns", "The file has columns that are not in the template.")
    for merged in ws.merged_cells.ranges:
        if merged.max_row >= 2:
            raise file_error(
                "merged_cells", f"Merged cells are not allowed in the data ({merged.coord})."
            )

    result = ParseResult()
    max_rows = get_settings().upload_max_rows
    # Bound the work even for sheets with huge formatted-but-empty areas.
    if (ws.max_row or 0) > max_rows * 10 + 1_000:
        raise file_error(
            "too_many_rows",
            "The sheet uses far more rows than the upload limit. Delete unused rows and try again.",
            413,
        )
    for cells in ws.iter_rows(min_row=2, max_col=max(max_col, len(HEADERS))):
        values = [c.value for c in cells]
        if all(v is None or (isinstance(v, str) and not v.strip()) for v in values):
            continue
        result.total_rows += 1
        if result.total_rows > max_rows:
            raise file_error(
                "too_many_rows", f"The file has more than {max_rows:,} data rows.", 413
            )
        _validate_row(cells, sales_date, tax_rate, result)
    if result.total_rows == 0:
        raise file_error("no_rows", "The file has no sales rows below the header.")
    return result


def _clean_item(value: object) -> tuple[str | None, str | None]:
    """Required free text: the item sold. Returns (item, problem)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, "Item is required."
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return None, "Item must be text."
    raw = str(value) if not isinstance(value, float) else format(Decimal(str(value)), "f")
    if any(ord(c) < 32 or ord(c) == 127 for c in raw if c not in "\t"):
        return None, "Item contains characters that are not allowed."
    item = " ".join(raw.split())
    if item.startswith(FORMULA_PREFIXES):
        return None, "Item must not start with =, +, - or @."
    if len(item) > ITEM_MAX:
        return None, f"Item must be at most {ITEM_MAX} characters."
    return item, None


def tax_for(amount: Decimal, tax_rate: Decimal) -> tuple[Decimal, Decimal]:
    """Tax exclusive: (sales tax, net amount), each rounded ROUND_HALF_UP to 2 places."""
    tax = (amount * tax_rate / 100).quantize(CENT, ROUND_HALF_UP)
    return tax, amount + tax


def _validate_row(cells: tuple, sales_date: date, tax_rate: Decimal, result: ParseResult) -> None:  # type: ignore[type-arg]
    row = cells[0].row
    errors_before = result.error_count

    def err(column: str | None, code: str, message: str) -> None:
        result.add(row, column, code, message)

    for cell in cells:
        if cell.data_type == "f":
            err(
                HEADERS[cell.column - 1] if cell.column <= len(HEADERS) else None,
                "formula_not_allowed",
                f"Cell {cell.coordinate} contains a formula. Type the value instead.",
            )
        elif cell.data_type == "e":
            err(None, "cell_error", f"Cell {cell.coordinate} contains an Excel error value.")
        elif cell.column > len(HEADERS) and cell.value not in (None, ""):
            err(
                None, "unexpected_value", f"Cell {cell.coordinate} is outside the template columns."
            )
    if result.error_count > errors_before:
        return  # never interpret formulas or stray content

    raw = {HEADERS[i]: cells[i] for i in range(len(HEADERS))}

    sale_date, problem = _parse_date(raw["Date"].value)
    if problem:
        err("Date", "invalid_date", problem)
    elif sale_date is not None and sale_date != sales_date:
        err(
            "Date",
            "date_mismatch",
            f"Date {display_date(sale_date)} does not match the selected sales date "
            f"{display_date(sales_date)}.",
        )

    sale_time, problem = _parse_time(raw["Time"].value)
    if problem:
        err("Time", "invalid_time", problem)

    item, problem = _clean_item(raw["Item"].value)
    if problem:
        err("Item", "invalid_item", problem)

    name: str | None = None
    name_value = raw["Customer Name"].value
    if name_value is not None and not isinstance(name_value, str | int):
        err("Customer Name", "invalid_text", "Customer Name must be text.")
    elif name_value is not None:
        name = " ".join(str(name_value).split()) or None
        if name and any(ord(c) < 32 or ord(c) == 127 for c in str(name_value)):
            err(
                "Customer Name",
                "invalid_text",
                "Customer Name contains characters that are not allowed.",
            )
        elif name and name.startswith(FORMULA_PREFIXES):
            err("Customer Name", "invalid_text", "Customer Name must not start with =, +, - or @.")
        elif name and len(name) > NAME_MAX:
            err(
                "Customer Name",
                "invalid_text",
                f"Customer Name must be at most {NAME_MAX} characters.",
            )

    cnic: str | None = None
    cnic_value = raw["CNIC/NTN"].value
    if isinstance(cnic_value, int | float) and not isinstance(cnic_value, bool):
        err(
            "CNIC/NTN",
            "cnic_not_text",
            "CNIC/NTN is stored as a number, which loses leading zeros. Format the cell as Text.",
        )
    elif cnic_value is not None and not isinstance(cnic_value, str):
        err("CNIC/NTN", "invalid_cnic", "CNIC/NTN must be text.")
    else:
        cnic = _text(cnic_value)
        if cnic and not CNIC_RE.match(cnic):
            err(
                "CNIC/NTN",
                "invalid_cnic",
                "CNIC/NTN may contain only letters, digits and hyphens (at most 20).",
            )

    def number(
        column: str, places: int, *, positive: bool = False, maximum: Decimal = MAX_MONEY
    ) -> Decimal | None:
        cell = raw[column]
        value, problem = _decimal(cell.value)
        if problem:
            err(column, "invalid_number", f"{column} {problem}.")
            return None
        assert value is not None
        if _places(value) > places:
            err(column, "too_many_decimals", f"{column} has more than {places} decimal places.")
            return None
        if positive and value <= 0:
            err(column, "invalid_number", f"{column} must be more than 0.")
            return None
        if value > maximum:
            err(column, "invalid_number", f"{column} is too large.")
            return None
        return value

    quantity = number("Quantity", 3, positive=True, maximum=Decimal("99999999999.999"))
    rate = number("Rate", 4)
    amount = number("Amount", 2)

    def compare(column: str, given: Decimal, expected: Decimal, rule: str) -> None:
        difference = abs(given - expected)
        if difference > TOLERANCE:
            err(
                column,
                "calculation_mismatch",
                f"{column} {_money(given)} does not equal {rule} ({_money(expected)}).",
            )
        elif difference > 0:
            result.rounding_differences += 1

    if quantity is not None and rate is not None and amount is not None:
        compare(
            "Amount", amount, (quantity * rate).quantize(CENT, ROUND_HALF_UP), "Quantity × Rate"
        )

    if result.error_count == errors_before:
        assert sale_date and sale_time and item and quantity is not None and rate is not None
        assert amount is not None
        tax, net = tax_for(amount, tax_rate)
        if net > MAX_MONEY:
            err("Amount", "invalid_number", "Amount is too large.")
            return
        result.rows.append(
            ParsedRow(
                row,
                sale_date,
                sale_time,
                item,
                name,
                cnic,
                quantity,
                rate,
                amount,
                tax_rate.quantize(RATE_PLACES),
                tax,
                net,
            )
        )
