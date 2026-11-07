"""User-facing date text: the application standard is DD/MM/YYYY.

Calendar dates read as ``07/11/2026`` (7 November 2026) and timestamps as
``07/11/2026 11:41`` (24-hour, Pakistan time). These helpers are only for text
people read (validation messages, emails). APIs, the database, audit metadata
and logs keep ISO 8601 values.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

DISPLAY_TZ = ZoneInfo("Asia/Karachi")


def display_date(value: date) -> str:
    """``date(2026, 11, 7)`` -> ``"07/11/2026"``."""
    return value.strftime("%d/%m/%Y")


def display_datetime(value: datetime) -> str:
    """An aware timestamp in Pakistan time: ``"07/11/2026 11:41"``."""
    return value.astimezone(DISPLAY_TZ).strftime("%d/%m/%Y %H:%M")
