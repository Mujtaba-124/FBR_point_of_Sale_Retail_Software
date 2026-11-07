"""Subscription reminder email content (HTML + plain text).

Every dynamic value is HTML-escaped in the HTML part. Header values come only
from validated settings (sender) and the stage (subject); EmailMessage refuses
CR/LF in headers, so header injection is not possible. The content contains no
links, credentials, session data or company business data.
"""

import html
from dataclasses import dataclass
from datetime import date

from app.core.dates import display_date
from app.services.reminder_schedule import ReminderStage

BRAND = "Cheena FBR POS"
PRODUCT = "Cheena FBR POS Software"


@dataclass(frozen=True)
class ReminderContent:
    subject: str
    text: str
    html: str


def _days(n: int) -> str:
    return f"{n} {'day' if n == 1 else 'days'}"


def format_date(value: date) -> str:
    return display_date(value)


def render_reminder(
    *, stage: ReminderStage, company_name: str, expiry_date: date, status_label: str
) -> ReminderContent:
    expiry = format_date(expiry_date)
    if stage.kind == "before_expiry":
        subject = f"{BRAND} — Subscription expires in {_days(stage.days)}"
        headline = f"Your subscription expires in {_days(stage.days)}"
        summary = (
            f"The {PRODUCT} subscription for {company_name} is valid until {expiry} "
            f"(inclusive). {_days(stage.days).capitalize()} remaining."
        )
        action = (
            "Please arrange the renewal before the expiry date so that Company Workspace "
            "access continues without interruption."
        )
        remaining = _days(stage.days)
        tone = "#b45309"
    elif stage.kind == "expiry_day":
        subject = f"{BRAND} — Subscription expires today"
        headline = "Your subscription expires today"
        summary = (
            f"Today, {expiry}, is the last valid day of the {PRODUCT} subscription for "
            f"{company_name}. The subscription remains valid until the end of today "
            "(Pakistan time)."
        )
        action = (
            "Renew today to avoid interruption. From tomorrow, Company Workspace access will "
            "be restricted until the subscription is renewed."
        )
        remaining = "Last valid day (today)"
        tone = "#b91c1c"
    else:
        subject = f"{BRAND} — Subscription expired {_days(stage.days)} ago"
        headline = f"Your subscription expired {_days(stage.days)} ago"
        summary = (
            f"The {PRODUCT} subscription for {company_name} expired on {expiry}. "
            "Company Workspace access is restricted until the subscription is renewed."
        )
        action = (
            "Renew the subscription to restore Company Workspace access. Your data is kept; "
            "access returns as soon as the renewal is recorded."
        )
        remaining = f"Expired {_days(stage.days)} ago"
        tone = "#b91c1c"

    guidance = (
        "Renewals are recorded by the Super Admin in Super Admin › Subscription Management. "
        "If you are not the Super Admin, please contact your Cheena FBR POS administrator."
    )
    footer = (
        f"This is an automated message from {PRODUCT}. Please do not reply. You receive it "
        "because your account is set to receive subscription notices."
    )

    rows = [
        ("Company", company_name),
        ("Subscription expiry date", f"{expiry} (inclusive)"),
        ("Remaining", remaining),
        ("Current status", status_label),
    ]

    text = "\n".join(
        [
            headline,
            "",
            summary,
            "",
            *[f"{label}: {value}" for label, value in rows],
            "",
            "What to do",
            action,
            guidance,
            "",
            "-- ",
            footer,
            "",
        ]
    )

    e = html.escape
    table_rows = "".join(
        '<tr><td style="padding:8px 0;color:#64748b;font-size:14px;">'
        f"{e(label)}</td>"
        '<td style="padding:8px 0;color:#0f172a;font-size:14px;font-weight:600;'
        f'text-align:right;">{e(value)}</td></tr>'
        for label, value in rows
    )
    html_body = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(subject)}</title>
</head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Segoe UI,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
 style="max-width:560px;background:#ffffff;border-radius:12px;overflow:hidden;
 border:1px solid #e2e8f0;">
<tr><td style="background:#0b1a3d;padding:18px 24px;">
<div style="color:#ffffff;font-size:18px;font-weight:700;">Cheena</div>
<div style="color:#93c5fd;font-size:11px;letter-spacing:2px;">FBR POS SOFTWARE</div>
</td></tr>
<tr><td style="padding:24px;">
<h1 style="margin:0 0 12px;font-size:20px;line-height:1.3;color:{tone};">{e(headline)}</h1>
<p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#334155;">{e(summary)}</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
 style="border-top:1px solid #e2e8f0;border-bottom:1px solid #e2e8f0;margin:0 0 16px;">
{table_rows}
</table>
<h2 style="margin:0 0 8px;font-size:15px;color:#0f172a;">What to do</h2>
<p style="margin:0 0 8px;font-size:14px;line-height:1.6;color:#334155;">{e(action)}</p>
<p style="margin:0;font-size:14px;line-height:1.6;color:#334155;">{e(guidance)}</p>
</td></tr>
<tr><td style="padding:16px 24px;background:#f8fafc;border-top:1px solid #e2e8f0;">
<p style="margin:0;font-size:12px;line-height:1.5;color:#64748b;">{e(footer)}</p>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""
    return ReminderContent(subject=subject, text=text, html=html_body)
