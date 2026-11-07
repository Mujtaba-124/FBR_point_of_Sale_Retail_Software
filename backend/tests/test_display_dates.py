"""The DD/MM/YYYY standard for dates in text people read (messages, emails)."""

from datetime import UTC, date, datetime

import pytest

from app.core.dates import display_date, display_datetime
from app.models import EmailSettings
from app.services.email_settings import build_test_message
from app.services.excel_sales import build_template
from app.services.reminder_schedule import ReminderStage
from app.services.reminder_templates import render_reminder


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (date(2026, 11, 7), "07/11/2026"),  # 7 November, not 11 July
        (date(2026, 7, 11), "11/07/2026"),
        (date(2027, 11, 5), "05/11/2027"),
        (date(2027, 1, 7), "07/01/2027"),
        (date(2026, 12, 31), "31/12/2026"),
        (date(2028, 2, 29), "29/02/2028"),
    ],
)
def test_calendar_dates_are_day_first(value: date, text: str) -> None:
    assert display_date(value) == text


def test_timestamps_are_shown_in_pakistan_time_24_hour() -> None:
    # 06:41 UTC is 11:41 in Pakistan (UTC+5); 19:30 UTC is already the next day there.
    assert display_datetime(datetime(2026, 11, 7, 6, 41, tzinfo=UTC)) == "07/11/2026 11:41"
    assert display_datetime(datetime(2026, 12, 31, 19, 30, tzinfo=UTC)) == "01/01/2027 00:30"


def test_reminder_emails_show_the_expiry_as_dd_mm_yyyy() -> None:
    content = render_reminder(
        stage=ReminderStage(-7),
        company_name="C",
        expiry_date=date(2027, 11, 5),
        status_label="Active",
    )
    assert "05/11/2027" in content.text
    assert "05/11/2027" in content.html
    assert "Nov" not in content.text


def test_the_smtp_test_email_shows_its_send_time_as_dd_mm_yyyy() -> None:
    row = EmailSettings(sender_name="Cheena", sender_email="noreply@example.test")
    message = build_test_message(
        row, "admin@example.test", datetime(2026, 11, 7, 6, 41, tzinfo=UTC)
    )
    assert "on 07/11/2026 11:41 PKT." in message.get_content()


def test_template_instructions_explain_accepted_date_cells() -> None:
    from io import BytesIO

    from openpyxl import load_workbook

    wb = load_workbook(BytesIO(build_template()), read_only=True)
    lines = (str(row[0]) for row in wb["Instructions"].iter_rows(values_only=True) if row[0])
    text = " ".join(" ".join(lines).split())  # the sheet wraps sentences across rows
    # The accepted text formats are unchanged; DD/MM/YYYY text is explained, not accepted.
    assert "2026-11-07 or 07-Nov-2026" in text
    assert "text such as 07/11/2026 is not accepted" in text
    assert "DD/MM/YYYY (07/11/2026 = 7 November 2026)" in text
    # Phase 4.2: real Excel date cells are shown day first, DD/MM/YYYY.
    assert wb["Sales"]["A2"].number_format == "dd/mm/yyyy"
