"""End-to-end verification of the subscription expiry reminder system.

Runs INSIDE the isolated QA stack started by ``scripts/qa/Invoke-ReminderE2E.ps1``:
a disposable ``*_e2e`` PostgreSQL database, Redis DB 12, a dedicated Celery
worker and Beat, and the file-sink transport (no email ever leaves the
machine). Application time is driven through the simulated clock
(``app.core.clock``); the Windows and Docker clocks are never touched.

Every reminder is created and sent by the real Celery pipeline: Beat triggers
``reminders.evaluate`` and ``email_outbox.dispatch`` on short intervals, and
this driver only moves the simulated time, injects SMTP faults, and checks the
database and the sink.

Exit status: 0 = every check passed, 1 = at least one check failed,
2 = refused to run (safety guard), 3 = unexpected error.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from email import message_from_bytes, policy
from email.message import EmailMessage
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select, text, update
from sqlalchemy.orm import sessionmaker

from app.celery_app import celery_app
from app.core import clock, secret_box
from app.core.config import get_settings
from app.core.redis import get_redis
from app.core.security import hash_password
from app.db.session import get_engine
from app.models import (
    AccessCategory,
    AppSubscription,
    AuditEvent,
    EmailDeliveryAttempt,
    EmailOutbox,
    EmailSettings,
    SubscriptionReminderSettings,
    User,
)
from app.models import reminders as m
from app.services import email_settings as email_svc
from app.services.reminder_outbox import BACKOFF_SECONDS, LEASE_SECONDS, MAX_ATTEMPTS
from app.services.reminder_schedule import ReminderStage
from app.services.reminder_templates import render_reminder
from app.services.smtp_transport import SINK_FAULTS_KEY
from app.services.subscription_renewal import renew_subscription

REDIS_DB = 12
SUPER = "e2e.super@example.test"
ADMIN = "e2e.admin@example.test"
INACTIVE_ADMIN = "e2e.former-admin@example.test"
STAFF = "e2e.staff@example.test"
COMPANY = "E2E Company <Reminders> & Co"

SCHEDULE_EXPIRY = date(2027, 3, 20)
RENEWAL_EXPIRY = date(2027, 6, 30)
FAULT_EXPIRY = date(2027, 9, 30)
BOUNDARY_OFFSETS = {-16, -15, 5, 6}
PKT_OFFSET = timedelta(hours=5)

SessionFactory = sessionmaker(bind=get_engine(), autoflush=False)


def pkt(day: date, hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    """The UTC instant of a Pakistan (UTC+5, no DST) local time."""
    local = datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=UTC)
    return local - PKT_OFFSET


# --- Result bookkeeping --------------------------------------------------------


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Section:
    title: str
    checks: list[Check] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def expect(self, name: str, condition: bool, detail: str = "") -> bool:
        self.checks.append(Check(name, bool(condition), detail))
        mark = "PASS" if condition else "FAIL"
        print(f"  [{mark}] {self.title}: {name}{(' - ' + detail) if detail else ''}", flush=True)
        return bool(condition)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)


# --- Environment helpers -------------------------------------------------------


class Refused(Exception):
    pass


def guard() -> str:
    """Refuse to run anywhere but the disposable QA stack."""
    s = get_settings()
    name = s.database_url.rsplit("/", 1)[-1].split("?", 1)[0]
    problems = []
    if not s.e2e_test_mode:
        problems.append("E2E_TEST_MODE is not enabled")
    if s.email_transport != "sink":
        problems.append("EMAIL_TRANSPORT is not 'sink'")
    if not name.endswith("_e2e") or name == "cheena_database":
        problems.append(f"database '{name}' is not a disposable *_e2e database")
    if get_redis().connection_pool.connection_kwargs.get("db") != REDIS_DB:
        problems.append(f"Redis must use logical database {REDIS_DB}")
    with SessionFactory() as db:
        if db.scalar(text("SELECT current_database()")) != name:
            problems.append("connected database does not match DATABASE_URL")
    if problems:
        raise Refused("; ".join(problems))
    return name


class Sink:
    def __init__(self, directory: str) -> None:
        self.dir = Path(directory)

    def clear(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        for f in self.dir.glob("*.eml"):
            f.unlink()

    def messages(self) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        if not self.dir.exists():
            return out
        for f in sorted(self.dir.glob("*.eml")):
            msg = cast(EmailMessage, message_from_bytes(f.read_bytes(), policy=policy.default))  # type: ignore[arg-type]
            html_part = msg.get_body(("html",))
            out.append(
                {
                    "to": str(msg["To"]),
                    "subject": str(msg["Subject"]),
                    "message_id": str(msg["Message-ID"]),
                    "html": html_part.get_content() if html_part is not None else "",
                }
            )
        return out


def wait_until(predicate: Callable[[], bool], timeout: float = 45.0, step: float = 0.25) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


def set_time(moment: datetime) -> None:
    clock.set_simulated_now(moment)


def last_run() -> tuple[datetime | None, str | None]:
    with SessionFactory() as db:
        s = db.get(SubscriptionReminderSettings, 1)
        assert s is not None
        return s.last_run_at, s.last_run_result


def wait_evaluated(moment: datetime, timeout: float = 45.0) -> str | None:
    """Wait for a Beat-triggered evaluation at exactly this simulated instant."""
    ok = wait_until(lambda: last_run()[0] == moment, timeout)
    return last_run()[1] if ok else None


def outbox_rows(**filters: Any) -> list[EmailOutbox]:
    with SessionFactory() as db:
        stmt = select(EmailOutbox)
        for key, value in filters.items():
            stmt = stmt.where(getattr(EmailOutbox, key) == value)
        rows = list(db.scalars(stmt.order_by(EmailOutbox.recipient_email)))
        db.expunge_all()
        return rows


def statuses(day: date) -> list[str]:
    return [r.status for r in outbox_rows(scheduled_date=day)]


def status_is(day: date, expected: list[str]) -> Callable[[], bool]:
    return lambda: statuses(day) == expected


def day_settled(day: date) -> Callable[[], bool]:
    return lambda: settled(outbox_rows(scheduled_date=day))


def attempt_outcomes(outbox_id: uuid.UUID) -> list[str]:
    with SessionFactory() as db:
        return list(
            db.scalars(
                select(EmailDeliveryAttempt.outcome)
                .where(EmailDeliveryAttempt.outbox_id == outbox_id)
                .order_by(EmailDeliveryAttempt.attempt_number)
            )
        )


def audit_actions() -> list[str]:
    with SessionFactory() as db:
        return list(db.scalars(select(AuditEvent.action).order_by(AuditEvent.occurred_at)))


def settled(rows: list[EmailOutbox]) -> bool:
    return bool(rows) and all(r.status not in (m.PENDING, m.PROCESSING) for r in rows)


def ping_worker(timeout: float = 60.0) -> bool:
    try:
        return celery_app.send_task("system.ping").get(timeout=timeout) == "pong"
    except Exception:
        return False


def push_faults(*codes: str) -> None:
    redis = get_redis()
    redis.delete(SINK_FAULTS_KEY)
    if codes:
        redis.rpush(SINK_FAULTS_KEY, *codes)


def expected_subject(offset: int, expiry: date) -> str:
    return render_reminder(
        stage=ReminderStage(offset), company_name=COMPANY, expiry_date=expiry, status_label="-"
    ).subject


# --- Disposable data -----------------------------------------------------------


def reset_data() -> None:
    with SessionFactory() as db:
        assert str(db.scalar(text("SELECT current_database()"))).endswith("_e2e")
        for table in (
            "email_delivery_attempts",
            "email_outbox",
            "authentication_sessions",
            "audit_events",
        ):
            db.execute(text(f"DELETE FROM {table}"))  # fixed names, not user input
        # Append-only trigger: bypassed only inside this disposable database.
        db.execute(text("SET LOCAL session_replication_role = replica"))
        db.execute(text("DELETE FROM subscription_renewals"))
        db.execute(text("SET LOCAL session_replication_role = origin"))
        db.execute(text("DELETE FROM email_settings"))
        db.execute(text("DELETE FROM app_subscription"))
        db.execute(text("DELETE FROM users"))
        db.execute(
            update(SubscriptionReminderSettings).values(
                is_enabled=False,
                notify_super_admin=True,
                notify_company_admin=True,
                version=1,
                last_run_at=None,
                last_run_business_date=None,
                last_run_result=None,
                last_run_details={},
            )
        )
        db.commit()
    push_faults()


def prepare(expiry: date, *, notify_company_admin: bool = True) -> None:
    """Fresh disposable data: 4 accounts, one subscription, SMTP (sink), reminders on."""
    reset_data()
    with SessionFactory() as db:
        for email_addr, category, active in (
            (SUPER, AccessCategory.SUPER_ADMIN, True),
            (ADMIN, AccessCategory.COMPANY_ADMIN, True),
            (INACTIVE_ADMIN, AccessCategory.COMPANY_ADMIN, False),
            (STAFF, AccessCategory.COMPANY_USER, True),
        ):
            db.add(
                User(
                    email=email_addr,
                    full_name=f"E2E {category.value}",
                    # Random, unknown password: these accounts are never signed in.
                    password_hash=hash_password(uuid.uuid4().hex + uuid.uuid4().hex),
                    access_category=category,
                    is_active=active,
                )
            )
        db.add(
            AppSubscription(
                company_name=COMPANY,
                start_date=expiry - timedelta(days=365),
                expiry_date=expiry,
            )
        )
        db.add(
            EmailSettings(
                smtp_host="smtp.e2e-reminders.invalid",
                smtp_port=587,
                encryption_mode="starttls",
                smtp_username="e2e.sender@example.test",
                encrypted_smtp_password=secret_box.encrypt(
                    "e2e-throwaway-" + uuid.uuid4().hex, email_svc.PASSWORD_PURPOSE
                ),
                sender_email="e2e.sender@example.test",
                sender_name="Cheena E2E",
                is_enabled=True,
            )
        )
        db.execute(
            update(SubscriptionReminderSettings).values(
                is_enabled=True, notify_company_admin=notify_company_admin
            )
        )
        db.commit()


# --- Verification phases -------------------------------------------------------


@dataclass
class DayResult:
    day: str
    utc_of_midnight_pkt: str
    offset: int
    stage: str
    expected_emails: int
    rows: int
    emails: int
    checks: list[Check]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)


def verify_schedule(sink: Sink, interval: float) -> tuple[list[DayResult], Section]:
    """Every day from 17 days before to 7 days after expiry (21 reminder days)."""
    print("== Schedule: 25 simulated days around expiry", SCHEDULE_EXPIRY, flush=True)
    prepare(SCHEDULE_EXPIRY)
    sink.clear()
    days: list[DayResult] = []
    for offset in range(-17, 8):
        day = SCHEDULE_EXPIRY + timedelta(days=offset)
        in_window = -15 <= offset <= 5
        sec = Section(f"{day} ({offset:+d})")
        stage = ReminderStage(offset).label if in_window else "outside schedule"

        midnight = pkt(day, 0, 0)
        set_time(midnight)
        result = wait_evaluated(midnight)
        sec.expect(
            "00:00 PKT: not sent before 09:00" if in_window else "00:00 PKT: no reminder",
            result == ("waiting_for_send_time" if in_window else "no_reminder_due"),
            f"result={result}, UTC={midnight:%Y-%m-%d %H:%M}",
        )
        sec.expect("00:00 PKT: nothing queued", not outbox_rows(scheduled_date=day))

        if offset in BOUNDARY_OFFSETS:
            before = pkt(day, 8, 59, 59)
            set_time(before)
            result = wait_evaluated(before)
            sec.expect(
                "08:59:59 PKT: still waiting" if in_window else "08:59:59 PKT: no reminder",
                result == ("waiting_for_send_time" if in_window else "no_reminder_due"),
                f"result={result}",
            )

        send_time = pkt(day, 10, 0)
        set_time(send_time)
        result = wait_evaluated(send_time)
        sec.expect(
            "10:00 PKT: evaluation",
            result == ("queued" if in_window else "no_reminder_due"),
            f"result={result}",
        )
        if in_window:
            wait_until(day_settled(day))
        rows = outbox_rows(scheduled_date=day)
        ids = {str(r.id) for r in rows}
        day_mail = [msg for msg in sink.messages() if any(i in msg["message_id"] for i in ids)]
        if in_window:
            sec.expect(
                "one row per recipient",
                sorted(r.recipient_email for r in rows) == sorted([ADMIN, SUPER]),
                f"rows={[r.recipient_email for r in rows]}",
            )
            sec.expect(
                "categories recorded",
                {r.recipient_email: r.recipient_categories for r in rows}
                == {SUPER: ["super_admin"], ADMIN: ["company_admin"]},
            )
            sec.expect(
                "accepted by SMTP sink",
                [r.status for r in rows] == [m.ACCEPTED, m.ACCEPTED],
                f"statuses={[r.status for r in rows]}",
            )
            sec.expect(
                "2 emails delivered to the sink",
                sorted(msg["to"] for msg in day_mail) == sorted([ADMIN, SUPER]),
                f"emails={len(day_mail)}",
            )
            subject = expected_subject(offset, SCHEDULE_EXPIRY)
            sec.expect(
                "subject",
                bool(day_mail) and all(msg["subject"] == subject for msg in day_mail),
                subject,
            )
            sec.expect(
                "company name HTML-escaped",
                bool(day_mail)
                and all(
                    "E2E Company &lt;Reminders&gt; &amp; Co" in msg["html"] for msg in day_mail
                ),
            )
        else:
            sec.expect("no rows", not rows, f"rows={len(rows)}")
            sec.expect("no emails", not day_mail)

        # Duplicate scheduler protection: Beat again plus extra manual signals.
        mail_before = len(sink.messages())
        dup_time = pkt(day, 10, 1)
        set_time(dup_time)
        for _ in range(3):
            celery_app.send_task("reminders.evaluate")
        celery_app.send_task("email_outbox.dispatch")
        result = wait_evaluated(dup_time)
        time.sleep(interval * 2 + 1)
        sec.expect(
            "repeated scheduler runs: no duplicates",
            len(outbox_rows(scheduled_date=day)) == len(rows)
            and len(sink.messages()) == mail_before,
            f"result={result}",
        )

        if offset in BOUNDARY_OFFSETS:
            late = pkt(day, 23, 59, 59)
            set_time(late)
            result = wait_evaluated(late)
            sec.expect(
                "23:59:59 PKT: same day, nothing new",
                result == ("already_queued" if in_window else "no_reminder_due")
                and len(outbox_rows(scheduled_date=day)) == len(rows),
                f"result={result}",
            )

        days.append(
            DayResult(
                day=day.isoformat(),
                utc_of_midnight_pkt=f"{midnight:%Y-%m-%d %H:%M} UTC",
                offset=offset,
                stage=stage,
                expected_emails=2 if in_window else 0,
                rows=len(rows),
                emails=len(day_mail),
                checks=sec.checks,
            )
        )
        print(f"{day} {offset:+3d} {'PASS' if days[-1].passed else 'FAIL'}", flush=True)

    totals = Section("Schedule totals")
    all_rows = outbox_rows()
    mail = sink.messages()
    reminder_days = {r.scheduled_date for r in all_rows}
    totals.expect("21 reminder dates", len(reminder_days) == 21, f"dates={len(reminder_days)}")
    totals.expect("42 recipient events", len(all_rows) == 42, f"rows={len(all_rows)}")
    totals.expect("42 emails accepted", len(mail) == 42, f"emails={len(mail)}")
    totals.expect(
        "Super Admin received 21",
        sum(1 for msg in mail if msg["to"] == SUPER) == 21,
    )
    totals.expect(
        "Company Admin received 21",
        sum(1 for msg in mail if msg["to"] == ADMIN) == 21,
    )
    totals.expect(
        "inactive Company Admin and Company User received none",
        not any(msg["to"] in (INACTIVE_ADMIN, STAFF) for msg in mail),
    )
    totals.expect(
        "every Message-ID unique",
        len({msg["message_id"] for msg in mail}) == len(mail),
    )
    totals.expect(
        "first and last reminder days",
        bool(reminder_days)
        and min(reminder_days) == SCHEDULE_EXPIRY - timedelta(days=15)
        and max(reminder_days) == SCHEDULE_EXPIRY + timedelta(days=5),
        f"{min(reminder_days, default=None)} .. {max(reminder_days, default=None)}",
    )
    totals.meta = {"dates": len(reminder_days), "events": len(all_rows), "emails": len(mail)}
    return days, totals


def verify_renewal(sink: Sink, interval: float) -> Section:
    print("== Renewal cancels outdated reminders", flush=True)
    sec = Section("Renewal")
    prepare(RENEWAL_EXPIRY)
    sink.clear()
    day = RENEWAL_EXPIRY - timedelta(days=3)
    push_faults("smtp_timeout", "smtp_timeout")  # keep both reminders queued (retry)
    moment = pkt(day, 10)
    set_time(moment)
    sec.expect("queued", wait_evaluated(moment) == "queued")
    sec.expect(
        "both waiting for retry",
        wait_until(
            lambda: [r.status for r in outbox_rows(scheduled_date=day)]
            == [m.RETRY_SCHEDULED, m.RETRY_SCHEDULED]
        ),
    )
    new_expiry = RENEWAL_EXPIRY + timedelta(days=365)
    with SessionFactory() as db:
        actor = db.scalar(select(User).where(User.email == SUPER))
        assert actor is not None
        renew_subscription(
            db,
            actor=actor,
            new_expiry_date=new_expiry,
            expected_expiry_date=RENEWAL_EXPIRY,
            idempotency_key=uuid.uuid4(),
        )
    rows = outbox_rows(scheduled_date=day)
    sec.expect(
        "queued reminders cancelled as obsolete",
        [(r.status, r.cancel_reason) for r in rows]
        == [(m.CANCELLED_OBSOLETE, "subscription_renewed")] * 2,
        f"{[(r.status, r.cancel_reason) for r in rows]}",
    )
    later = moment + timedelta(minutes=3)  # past the 1-minute retry backoff
    set_time(later)
    sec.expect("recalculated: nothing due today", wait_evaluated(later) == "no_reminder_due")
    time.sleep(interval * 2 + 1)
    sec.expect("obsolete reminders never sent", not sink.messages())
    sec.expect("history preserved", len(outbox_rows()) == 2)
    sec.expect(
        "audit: cancelled as obsolete", "reminder.jobs_cancelled_obsolete" in audit_actions()
    )

    new_day = new_expiry - timedelta(days=15)
    moment = pkt(new_day, 10)
    set_time(moment)
    sec.expect("new schedule queues", wait_evaluated(moment) == "queued")
    wait_until(lambda: settled(outbox_rows(scheduled_date=new_day)))
    new_rows = outbox_rows(scheduled_date=new_day)
    sec.expect(
        "new schedule delivers for the new expiry",
        [(r.status, r.expiry_date) for r in new_rows] == [(m.ACCEPTED, new_expiry)] * 2,
    )
    sec.expect(
        "new subject",
        sorted(msg["subject"] for msg in sink.messages())
        == [expected_subject(-15, new_expiry)] * 2,
    )
    return sec


def verify_failures(sink: Sink, interval: float) -> list[Section]:
    print("== Transient failures, retries, permanent failures, worker crashes", flush=True)
    prepare(FAULT_EXPIRY, notify_company_admin=False)  # one recipient: the Super Admin
    sink.clear()
    sections = []

    # 1. Transient failure, then success on retry.
    sec = Section("Transient failure then retry")
    day = FAULT_EXPIRY - timedelta(days=10)
    push_faults("smtp_timeout")
    moment = pkt(day, 10)
    set_time(moment)
    sec.expect("queued", wait_evaluated(moment) == "queued")
    sec.expect(
        "retry scheduled after timeout",
        wait_until(
            lambda: [
                (r.status, r.attempt_count, r.last_error_code)
                for r in outbox_rows(scheduled_date=day)
            ]
            == [(m.RETRY_SCHEDULED, 1, "smtp_timeout")]
        ),
    )
    retry_at = moment + timedelta(seconds=BACKOFF_SECONDS[0] + 1)
    set_time(retry_at)
    sec.expect(
        "accepted on the retry",
        wait_until(status_is(day, [m.ACCEPTED])),
    )
    row = outbox_rows(scheduled_date=day)[0]
    sec.expect(
        "attempts recorded",
        attempt_outcomes(row.id) == ["transient_failure", "accepted"],
        f"{attempt_outcomes(row.id)}",
    )
    sec.expect("one email", len(sink.messages()) == 1)
    sections.append(sec)

    # 2. Retry exhaustion with exponential backoff.
    sec = Section("Retry exhaustion")
    day = FAULT_EXPIRY - timedelta(days=9)
    push_faults(*["smtp_connection_refused"] * MAX_ATTEMPTS)
    moment = pkt(day, 10)
    set_time(moment)
    sec.expect("queued", wait_evaluated(moment) == "queued")
    for attempt, delay in enumerate(BACKOFF_SECONDS, start=1):

        def failed_attempt(a: int = attempt) -> bool:
            return [(r.status, r.attempt_count) for r in outbox_rows(scheduled_date=day)] == [
                (m.RETRY_SCHEDULED, a)
            ]

        reached = wait_until(failed_attempt)
        sec.expect(f"attempt {attempt} failed, retry in {delay}s", reached)
        moment += timedelta(seconds=delay + 1)
        set_time(moment)
    sec.expect(
        "failed permanently after the last attempt",
        wait_until(
            lambda: [(r.status, r.attempt_count) for r in outbox_rows(scheduled_date=day)]
            == [(m.FAILED_PERMANENT, MAX_ATTEMPTS)]
        ),
    )
    row = outbox_rows(scheduled_date=day)[0]
    sec.expect(
        "no more attempts later", _no_change_after(day, moment + timedelta(hours=1), interval)
    )
    sec.expect(
        "every attempt recorded",
        attempt_outcomes(row.id) == ["transient_failure"] * MAX_ATTEMPTS,
    )
    sec.expect("no new email", len(sink.messages()) == 1)
    sections.append(sec)

    # 3. Permanent rejection is not retried.
    sec = Section("Permanent failure")
    day = FAULT_EXPIRY - timedelta(days=8)
    push_faults("smtp_auth_failed")
    moment = pkt(day, 10)
    set_time(moment)
    sec.expect("queued", wait_evaluated(moment) == "queued")
    sec.expect(
        "failed permanently on the first attempt",
        wait_until(
            lambda: [
                (r.status, r.attempt_count, r.last_error_code)
                for r in outbox_rows(scheduled_date=day)
            ]
            == [(m.FAILED_PERMANENT, 1, "smtp_auth_failed")]
        ),
    )
    sec.expect("not retried", _no_change_after(day, moment + timedelta(hours=1), interval))
    sec.expect("no new email", len(sink.messages()) == 1)
    sections.append(sec)

    # 4/5. Worker process crashes during sending, before and after acceptance.
    for offset, fault, extra_mail in (
        (-7, "crash_before_accept", 1),
        (-6, "crash_after_accept", 2),
    ):
        sec = Section(f"Worker crash ({fault})")
        day = FAULT_EXPIRY + timedelta(days=offset)
        push_faults(fault)
        moment = pkt(day, 10)
        set_time(moment)
        sec.expect("queued", wait_evaluated(moment) == "queued")
        sec.expect(
            "row left in processing by the dead worker",
            wait_until(status_is(day, [m.PROCESSING])),
        )
        sec.expect("worker process restarted", ping_worker())
        row = outbox_rows(scheduled_date=day)[0]
        sec.expect("attempt still in progress", attempt_outcomes(row.id) == ["in_progress"])
        recover_at = moment + timedelta(seconds=LEASE_SECONDS + 1)
        set_time(recover_at)
        sec.expect(
            "recovered after the lease expired and accepted",
            wait_until(status_is(day, [m.ACCEPTED])),
        )
        sec.expect(
            "interrupted attempt marked uncertain",
            attempt_outcomes(row.id) == ["uncertain", "accepted"],
            f"{attempt_outcomes(row.id)}",
        )
        new_mail = _mail_for(sink, row.id)
        sec.expect(
            f"{extra_mail} message(s) in the sink",
            len(new_mail) == extra_mail,
            "at-least-once: a crash after acceptance can repeat the email"
            if extra_mail == 2
            else "",
        )
        sec.expect(
            "stable Message-ID",
            len({msg["message_id"] for msg in new_mail}) == 1,
        )
        sec.expect(
            "audit: delivery interrupted", "reminder.delivery_interrupted" in audit_actions()
        )
        sections.append(sec)
    return sections


def _mail_for(sink: Sink, outbox_id: uuid.UUID) -> list[dict[str, str]]:
    return [msg for msg in sink.messages() if str(outbox_id) in msg["message_id"]]


def _no_change_after(day: date, moment: datetime, interval: float) -> bool:
    before = [(r.status, r.attempt_count) for r in outbox_rows(scheduled_date=day)]
    set_time(moment)
    wait_evaluated(moment)
    time.sleep(interval * 2 + 1)
    return [(r.status, r.attempt_count) for r in outbox_rows(scheduled_date=day)] == before


def verify_preconditions(sink: Sink) -> Section:
    print("== Sending preconditions", flush=True)
    sec = Section("Preconditions")
    prepare(FAULT_EXPIRY)
    sink.clear()
    day = FAULT_EXPIRY - timedelta(days=2)
    with SessionFactory() as db:
        db.execute(update(SubscriptionReminderSettings).values(is_enabled=False))
        db.commit()
    moment = pkt(day, 10)
    set_time(moment)
    sec.expect("reminders disabled: nothing queued", wait_evaluated(moment) == "reminders_disabled")
    with SessionFactory() as db:
        db.execute(update(SubscriptionReminderSettings).values(is_enabled=True))
        db.execute(update(EmailSettings).values(is_enabled=False))
        db.commit()
    moment += timedelta(minutes=1)
    set_time(moment)
    sec.expect(
        "email sending disabled: nothing queued",
        wait_evaluated(moment) == "email_sending_disabled",
    )
    with SessionFactory() as db:
        db.execute(text("DELETE FROM email_settings"))
        db.commit()
    moment += timedelta(minutes=1)
    set_time(moment)
    sec.expect("SMTP missing: nothing queued", wait_evaluated(moment) == "email_not_configured")
    sec.expect("no rows, no emails", not outbox_rows() and not sink.messages())
    return sec


# --- Report --------------------------------------------------------------------


def write_report(
    path: Path,
    run_id: str,
    database: str,
    days: list[DayResult],
    sections: list[Section],
    started: datetime,
) -> bool:
    passed = all(d.passed for d in days) and all(s.passed for s in sections)
    lines = [
        "# Subscription reminder end-to-end verification",
        "",
        f"- Run: `{run_id}`  ",
        f"- Started (real UTC): {started:%Y-%m-%d %H:%M:%S}  ",
        f"- Database: `{database}` (disposable) · Redis DB {REDIS_DB} · transport: file sink  ",
        "- Time: simulated application clock (Asia/Karachi days); system clocks unchanged  ",
        f"- Expiry under test: {SCHEDULE_EXPIRY} (valid through that day)  ",
        f"- **Overall: {'PASS' if passed else 'FAIL'}**",
        "",
        "## Per-day results",
        "",
        "| Date (PKT) | Offset | Stage | 00:00 PKT in UTC | Expected | Rows | Emails | Result |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for d in days:
        lines.append(
            f"| {d.day} | {d.offset:+d} | {d.stage} | {d.utc_of_midnight_pkt} | "
            f"{d.expected_emails} | {d.rows} | {d.emails} | {'PASS' if d.passed else '**FAIL**'} |"
        )
    failed_days = [d for d in days if not d.passed]
    if failed_days:
        lines += ["", "### Failed day checks", ""]
        for d in failed_days:
            for c in d.checks:
                if not c.passed:
                    lines.append(f"- {d.day}: {c.name} — {c.detail}")
    lines += ["", "## Scenarios", ""]
    for s in sections:
        lines += [f"### {s.title}: {'PASS' if s.passed else 'FAIL'}", ""]
        for c in s.checks:
            detail = f" — {c.detail}" if c.detail else ""
            lines.append(f"- {'PASS' if c.passed else '**FAIL**'} {c.name}{detail}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.with_suffix(".json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "passed": passed,
                "days": [{**asdict(d), "passed": d.passed} for d in days],
                "sections": [
                    {"title": s.title, "passed": s.passed, "checks": [asdict(c) for c in s.checks]}
                    for s in sections
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return passed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=datetime.now(UTC).strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--report-dir", default="/app/.qa-e2e/reports")
    args = parser.parse_args(argv)
    started = datetime.now(UTC)
    try:
        database = guard()
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    settings = get_settings()
    interval = max(
        settings.reminder_evaluate_interval_seconds or 0,
        settings.outbox_dispatch_interval_seconds,
    )
    if not settings.reminder_evaluate_interval_seconds or interval > 10:
        print("REFUSED: set short Beat intervals for the e2e run", file=sys.stderr)
        return 2
    sink = Sink(settings.email_sink_dir)
    report = Path(args.report_dir) / f"reminder-e2e-{args.run_id}.md"
    days: list[DayResult] = []
    sections: list[Section] = []
    try:
        infra = Section("Infrastructure")
        infra.expect("Celery worker answers ping", ping_worker())
        sections.append(infra)
        set_time(pkt(SCHEDULE_EXPIRY - timedelta(days=40), 10))
        beat_alive = wait_until(lambda: last_run()[0] is not None, 30)
        infra.expect("Celery Beat triggers evaluations", beat_alive)
        days, totals = verify_schedule(sink, interval)
        sections.append(totals)
        sections.append(verify_renewal(sink, interval))
        sections.extend(verify_failures(sink, interval))
        sections.append(verify_preconditions(sink))
    except Exception:
        traceback.print_exc()
        crash = Section("Driver")
        crash.expect("completed without an unexpected error", False, traceback.format_exc(limit=3))
        sections.append(crash)
    finally:
        push_faults()
    passed = write_report(report, args.run_id, database, days, sections, started)
    print(f"\nReport: {report}")
    day_pass = sum(1 for d in days if d.passed)
    print(
        f"Days: {day_pass}/{len(days)} PASS; scenarios: "
        f"{sum(1 for s in sections if s.passed)}/{len(sections)} PASS"
    )
    print("OVERALL:", "PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
