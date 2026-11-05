"""Subscription expiry reminders: schedule, outbox, delivery, renewal, API.

Time is controlled through ``app.core.clock.utcnow`` (never the system clock).
Every send goes through ``ScriptedTransport``; no real SMTP traffic happens.
"""

import logging
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from email.message import EmailMessage

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.core import clock, secret_box
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
from app.services import email_settings as email_svc
from app.services import reminder_outbox as outbox
from app.services.reminder_schedule import ReminderStage, resolve_recipients, stage_for
from app.services.reminder_templates import render_reminder
from app.services.smtp_transport import SmtpConfig, failure
from app.services.subscription_renewal import renew_subscription
from tests.conftest import csrf_header, login

EXPIRY = date(2027, 3, 20)
SMTP_PASSWORD = "smtp-secret-" + uuid.uuid4().hex[:8]
ORIGIN = {"Origin": "http://localhost:3000"}
URL = "/api/v1/super-admin/email-settings"


def pkt(day: date, hour: int = 10, minute: int = 0) -> datetime:
    """A UTC instant for the given Pakistan local time (PKT = UTC+5)."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC) - timedelta(hours=5)


class ScriptedTransport:
    """Fake SMTP transport. ``script`` holds failure codes to raise in order."""

    def __init__(self, script: list[str | None] | None = None, delay: float = 0.0) -> None:
        self.script = list(script or [])
        self.delay = delay
        self.sent: list[EmailMessage] = []
        self.calls = 0
        self.lock = threading.Lock()

    def check_connection(self, config: SmtpConfig) -> None:
        return None

    def send(self, config: SmtpConfig, message: EmailMessage) -> None:
        assert config.password == SMTP_PASSWORD
        if self.delay:
            time.sleep(self.delay)
        with self.lock:
            self.calls += 1
            code = self.script.pop(0) if self.script else None
            if code:
                raise failure(code)
            self.sent.append(message)


@pytest.fixture
def at(monkeypatch: pytest.MonkeyPatch) -> Callable[[datetime], None]:
    def _set(moment: datetime) -> None:
        monkeypatch.setattr(clock, "utcnow", lambda: moment)

    return _set


@pytest.fixture
def factory() -> Callable[[], Session]:
    return sessionmaker(bind=get_engine(), autoflush=False)


def add_user(db: Session, category: AccessCategory, email: str, active: bool = True) -> User:
    user = User(
        email=email,
        full_name=f"Reminder {category.value}",
        password_hash="not-a-real-hash",
        access_category=category,
        is_active=active,
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def world(db: Session) -> Session:
    """Subscription expiring EXPIRY, SMTP configured + enabled, reminders on,
    one Super Admin and one Company Admin."""
    db.add(
        AppSubscription(
            company_name="Cheena & Sons <Pvt>",
            start_date=EXPIRY - timedelta(days=365),
            expiry_date=EXPIRY,
        )
    )
    db.add(
        EmailSettings(
            smtp_host="smtp.example.com",
            smtp_port=587,
            encryption_mode="starttls",
            smtp_username="sender@example.com",
            encrypted_smtp_password=secret_box.encrypt(SMTP_PASSWORD, email_svc.PASSWORD_PURPOSE),
            sender_email="sender@example.com",
            sender_name="Cheena POS",
            is_enabled=True,
        )
    )
    db.execute(update(SubscriptionReminderSettings).values(is_enabled=True))
    db.commit()
    add_user(db, AccessCategory.SUPER_ADMIN, "owner@example.test")
    add_user(db, AccessCategory.COMPANY_ADMIN, "admin@example.test")
    return db


def rows(db: Session) -> list[EmailOutbox]:
    db.expire_all()
    return list(db.scalars(select(EmailOutbox).order_by(EmailOutbox.recipient_email)))


def actions(db: Session, prefix: str = "reminder.") -> list[str]:
    db.expire_all()
    return list(
        db.scalars(
            select(AuditEvent.action)
            .where(AuditEvent.action.startswith(prefix))
            .order_by(AuditEvent.occurred_at, AuditEvent.id)
        )
    )


def evaluate(factory: Callable[[], Session]) -> outbox.EvaluationResult:
    with factory() as db:
        return outbox.evaluate(db)


def dispatch(factory: Callable[[], Session], transport: ScriptedTransport) -> outbox.DispatchResult:
    return outbox.dispatch_due(factory, transport, worker="test-worker")


# --- Schedule ----------------------------------------------------------------


@pytest.mark.parametrize("offset", range(-15, 6))
def test_every_scheduled_day_sends_one_reminder_per_recipient(
    world: Session, factory, at, offset: int
) -> None:
    day = EXPIRY + timedelta(days=offset)
    at(pkt(day))
    result = evaluate(factory)
    assert result.result == "queued" and result.queued == 2
    transport = ScriptedTransport()
    dispatch(factory, transport)
    assert len(transport.sent) == 2
    subjects = {m["Subject"] for m in transport.sent}
    if offset < 0:
        n = -offset
        expected = f"Cheena FBR POS — Subscription expires in {n} {'day' if n == 1 else 'days'}"
    elif offset == 0:
        expected = "Cheena FBR POS — Subscription expires today"
    else:
        expected = (
            f"Cheena FBR POS — Subscription expired {offset} {'day' if offset == 1 else 'days'} ago"
        )
    assert subjects == {expected}
    assert {r.status for r in rows(world)} == {"accepted"}
    assert {r.days_offset for r in rows(world)} == {offset}


@pytest.mark.parametrize("offset", [-30, -16, 6, 7, 40])
def test_no_reminder_outside_the_schedule(world: Session, factory, at, offset: int) -> None:
    at(pkt(EXPIRY + timedelta(days=offset)))
    assert evaluate(factory).result == "no_reminder_due"
    assert rows(world) == []


def test_no_reminder_before_subscription_start(db: Session, factory, at) -> None:
    db.add(
        AppSubscription(
            company_name="Short", start_date=EXPIRY - timedelta(days=5), expiry_date=EXPIRY
        )
    )
    db.commit()
    at(pkt(EXPIRY - timedelta(days=10)))
    assert outbox.due_stage(db.get(AppSubscription, 1), EXPIRY - timedelta(days=10)) is None


def test_pakistan_timezone_boundary(world: Session, factory, at) -> None:
    first_day = EXPIRY - timedelta(days=15)
    # 23:59 PKT on the day before the window: still outside the schedule.
    at(pkt(first_day - timedelta(days=1), 23, 59))
    assert evaluate(factory).result == "no_reminder_due"
    # 00:00 PKT on the first day (19:00 UTC the previous day): due, but before send time.
    at(datetime(first_day.year, first_day.month, first_day.day, tzinfo=UTC) - timedelta(hours=5))
    assert evaluate(factory).result == "waiting_for_send_time"
    assert rows(world) == []
    # 09:00 PKT: queued, for the PKT calendar date.
    at(pkt(first_day, 9, 0))
    assert evaluate(factory).result == "queued"
    assert {r.scheduled_date for r in rows(world)} == {first_day}


def test_last_post_expiry_day_and_stop(world: Session, factory, at) -> None:
    at(pkt(EXPIRY + timedelta(days=5)))
    assert evaluate(factory).queued == 2
    at(pkt(EXPIRY + timedelta(days=6)))
    assert evaluate(factory).result == "no_reminder_due"


def test_stage_labels() -> None:
    assert stage_for(EXPIRY, EXPIRY - timedelta(days=1)) == ReminderStage(-1)
    assert ReminderStage(-1).label == "1 day before expiry"
    assert ReminderStage(0).label == "Expiry day"
    assert ReminderStage(3).label == "3 days after expiry"
    assert stage_for(EXPIRY, EXPIRY + timedelta(days=6)) is None


# --- Idempotency and concurrency ---------------------------------------------


def test_repeated_scheduler_runs_create_no_duplicates(world: Session, factory, at) -> None:
    at(pkt(EXPIRY - timedelta(days=3)))
    assert evaluate(factory).queued == 2
    for _ in range(3):
        result = evaluate(factory)
        assert result.queued == 0 and result.already_queued == 2
    transport = ScriptedTransport()
    dispatch(factory, transport)
    dispatch(factory, transport)
    evaluate(factory)
    dispatch(factory, transport)
    assert len(transport.sent) == 2
    assert len(rows(world)) == 2


def test_parallel_scheduler_runs(world: Session, factory, at) -> None:
    at(pkt(EXPIRY - timedelta(days=2)))
    errors: list[BaseException] = []

    def run() -> None:
        try:
            evaluate(factory)
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(rows(world)) == 2


def test_parallel_workers_never_send_the_same_row(world: Session, factory, at) -> None:
    for i in range(6):
        add_user(world, AccessCategory.COMPANY_ADMIN, f"extra{i}@example.test")
    at(pkt(EXPIRY - timedelta(days=1)))
    assert evaluate(factory).queued == 8
    transport = ScriptedTransport(delay=0.05)
    threads = [
        threading.Thread(
            target=outbox.dispatch_due, args=(factory, transport), kwargs={"worker": f"w{i}"}
        )
        for i in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    recipients = [m["To"] for m in transport.sent]
    assert len(recipients) == 8 and len(set(recipients)) == 8
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(EmailDeliveryAttempt)) == 8
    assert {r.status for r in rows(world)} == {"accepted"}


# --- Recipients ----------------------------------------------------------------


def test_recipient_deduplication(world: Session) -> None:
    # Same mailbox reachable through both categories (stored with spacing/case
    # differences that the case-insensitive unique index allows).
    world.execute(
        text(
            "UPDATE users SET email = '  Admin@Example.test ' WHERE access_category = 'super_admin'"
        )
    )
    world.commit()
    res = resolve_recipients(world, notify_super_admin=True, notify_company_admin=True)
    assert [(r.email, sorted(r.categories)) for r in res.recipients] == [
        ("admin@example.test", ["company_admin", "super_admin"])
    ]


def test_deduplicated_recipient_gets_one_email(world: Session, factory, at) -> None:
    world.execute(
        text("UPDATE users SET email = ' ADMIN@example.test' WHERE access_category = 'super_admin'")
    )
    world.commit()
    at(pkt(EXPIRY))
    assert evaluate(factory).queued == 1
    transport = ScriptedTransport()
    dispatch(factory, transport)
    assert len(transport.sent) == 1
    assert sorted(rows(world)[0].recipient_categories) == ["company_admin", "super_admin"]


def test_inactive_company_admin_and_company_users_excluded(world: Session) -> None:
    add_user(world, AccessCategory.COMPANY_ADMIN, "gone@example.test", active=False)
    add_user(world, AccessCategory.COMPANY_USER, "staff@example.test")
    res = resolve_recipients(world, notify_super_admin=True, notify_company_admin=True)
    assert {r.email for r in res.recipients} == {"owner@example.test", "admin@example.test"}


def test_ambiguous_super_admin_is_not_selected(world: Session) -> None:
    add_user(world, AccessCategory.SUPER_ADMIN, "second@example.test")
    res = resolve_recipients(world, notify_super_admin=True, notify_company_admin=False)
    assert res.super_admin_status == "ambiguous" and res.recipients == []


def test_category_switches(world: Session, factory, at) -> None:
    world.execute(update(SubscriptionReminderSettings).values(notify_company_admin=False))
    world.commit()
    at(pkt(EXPIRY - timedelta(days=4)))
    evaluate(factory)
    assert [r.recipient_email for r in rows(world)] == ["owner@example.test"]


# --- Preconditions -------------------------------------------------------------


def test_email_sending_disabled(world: Session, factory, at) -> None:
    world.execute(update(EmailSettings).values(is_enabled=False))
    world.commit()
    at(pkt(EXPIRY - timedelta(days=2)))
    assert evaluate(factory).result == "email_sending_disabled"
    assert rows(world) == []


def test_reminders_disabled(world: Session, factory, at) -> None:
    world.execute(update(SubscriptionReminderSettings).values(is_enabled=False))
    world.commit()
    at(pkt(EXPIRY - timedelta(days=2)))
    assert evaluate(factory).result == "reminders_disabled"
    assert rows(world) == []


def test_missing_smtp_configuration(world: Session, factory, at) -> None:
    world.execute(text("DELETE FROM email_settings"))
    world.commit()
    at(pkt(EXPIRY - timedelta(days=2)))
    assert evaluate(factory).result == "email_not_configured"
    assert rows(world) == []


def test_missing_subscription(db: Session, factory, at) -> None:
    db.execute(update(SubscriptionReminderSettings).values(is_enabled=True))
    db.commit()
    at(pkt(EXPIRY))
    assert evaluate(factory).result == "subscription_not_configured"


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("UPDATE email_settings SET is_enabled = false", "email_sending_disabled"),
        ("UPDATE subscription_reminder_settings SET is_enabled = false", "reminders_disabled"),
        ("DELETE FROM email_settings", "email_not_configured"),
        (
            "UPDATE users SET is_active = false WHERE email = 'admin@example.test'",
            "recipient_not_eligible",
        ),
        (
            "UPDATE subscription_reminder_settings SET notify_company_admin = false",
            "recipient_not_eligible",
        ),
    ],
)
def test_conditions_are_rechecked_before_each_send(
    world: Session, factory, at, change: str, reason: str
) -> None:
    at(pkt(EXPIRY - timedelta(days=2)))
    evaluate(factory)
    world.execute(text(change))
    world.commit()
    transport = ScriptedTransport()
    dispatch(factory, transport)
    by_email = {r.recipient_email: r for r in rows(world)}
    admin_row = by_email["admin@example.test"]
    assert admin_row.status == "cancelled" and admin_row.cancel_reason == reason
    assert "admin@example.test" not in [m["To"] for m in transport.sent]
    assert admin_row.attempt_count == 0


def test_unreadable_password_fails_without_sending(
    world: Session, factory, at, monkeypatch: pytest.MonkeyPatch
) -> None:
    import base64
    import secrets

    from app.core.config import get_settings

    at(pkt(EXPIRY - timedelta(days=2)))
    evaluate(factory)
    monkeypatch.setattr(
        get_settings(),
        "email_settings_encryption_key",
        base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    )
    transport = ScriptedTransport()
    dispatch(factory, transport)
    assert transport.calls == 0
    assert {(r.status, r.last_error_code) for r in rows(world)} == {
        ("failed_permanent", "stored_password_unreadable")
    }


# --- SMTP failures and retries -------------------------------------------------


def test_transient_error_is_retried_with_backoff(world: Session, factory, at) -> None:
    world.execute(update(SubscriptionReminderSettings).values(notify_company_admin=False))
    world.commit()
    start = pkt(EXPIRY - timedelta(days=5))
    at(start)
    evaluate(factory)
    transport = ScriptedTransport(["smtp_timeout"])
    dispatch(factory, transport)
    row = rows(world)[0]
    assert row.status == "retry_scheduled" and row.last_error_code == "smtp_timeout"
    assert row.next_attempt_at == start + timedelta(seconds=outbox.BACKOFF_SECONDS[0])
    dispatch(factory, transport)  # not due yet
    assert transport.calls == 1
    at(start + timedelta(seconds=61))
    dispatch(factory, transport)
    row = rows(world)[0]
    assert row.status == "accepted" and row.attempt_count == 2
    assert len(transport.sent) == 1
    with factory() as db:
        outcomes = db.scalars(
            select(EmailDeliveryAttempt.outcome).order_by(EmailDeliveryAttempt.attempt_number)
        ).all()
    assert outcomes == ["transient_failure", "accepted"]


def test_permanent_error_is_not_retried(world: Session, factory, at) -> None:
    world.execute(update(SubscriptionReminderSettings).values(notify_company_admin=False))
    world.commit()
    at(pkt(EXPIRY - timedelta(days=5)))
    evaluate(factory)
    transport = ScriptedTransport(["smtp_auth_failed"])
    dispatch(factory, transport)
    row = rows(world)[0]
    assert row.status == "failed_permanent" and row.attempt_count == 1
    assert row.last_error_code == "smtp_auth_failed"


def test_retry_exhaustion(world: Session, factory, at) -> None:
    world.execute(update(SubscriptionReminderSettings).values(notify_company_admin=False))
    world.commit()
    moment = pkt(EXPIRY - timedelta(days=5), 9, 0)
    at(moment)
    evaluate(factory)
    transport = ScriptedTransport(["smtp_connection_refused"] * 10)
    for _ in range(outbox.MAX_ATTEMPTS + 2):
        dispatch(factory, transport)
        moment += timedelta(hours=1)
        at(moment)
    row = rows(world)[0]
    assert row.status == "failed_permanent"
    assert row.attempt_count == outbox.MAX_ATTEMPTS == transport.calls
    assert row.last_error_code == "smtp_connection_refused"


def test_worker_crash_is_recovered_and_retried(world: Session, factory, at) -> None:
    world.execute(update(SubscriptionReminderSettings).values(notify_company_admin=False))
    world.commit()
    start = pkt(EXPIRY - timedelta(days=5))
    at(start)
    evaluate(factory)
    with factory() as db:
        claim = outbox.claim_next(db, worker="crashed-worker")
    assert isinstance(claim, outbox.Claim)  # claimed, then the worker "dies"
    row = rows(world)[0]
    assert row.status == "processing" and row.lease_expires_at is not None

    transport = ScriptedTransport()
    dispatch(factory, transport)  # lease still valid: nobody touches it
    assert transport.calls == 0

    at(start + timedelta(seconds=outbox.LEASE_SECONDS + 1))
    result = dispatch(factory, transport)
    assert result.recovered == 1
    row = rows(world)[0]
    assert row.status == "accepted" and row.attempt_count == 2
    with factory() as db:
        outcomes = db.scalars(
            select(EmailDeliveryAttempt.outcome).order_by(EmailDeliveryAttempt.attempt_number)
        ).all()
    assert outcomes == ["uncertain", "accepted"]
    # Same Message-ID as the interrupted attempt, so a duplicate is recognisable.
    assert transport.sent[0]["Message-ID"] == claim.message["Message-ID"]
    assert "reminder.delivery_interrupted" in actions(world)


def test_late_result_after_recovery_keeps_acceptance(world: Session, factory, at) -> None:
    world.execute(update(SubscriptionReminderSettings).values(notify_company_admin=False))
    world.commit()
    start = pkt(EXPIRY - timedelta(days=5))
    at(start)
    evaluate(factory)
    with factory() as db:
        claim = outbox.claim_next(db, worker="slow-worker")
    assert isinstance(claim, outbox.Claim)
    at(start + timedelta(seconds=outbox.LEASE_SECONDS + 1))
    with factory() as db:
        outbox.recover_expired_leases(db)
    with factory() as db:
        status = outbox.deliver(db, claim, ScriptedTransport())
    assert status == "accepted"


def test_missed_days_are_not_backfilled(world: Session, factory, at) -> None:
    at(pkt(EXPIRY - timedelta(days=6)))
    evaluate(factory)  # queued, but the worker is down all day
    at(pkt(EXPIRY - timedelta(days=4)))
    result = evaluate(factory)
    assert result.cancelled_missed == 2 and result.queued == 2
    transport = ScriptedTransport()
    dispatch(factory, transport)
    assert {m["Subject"] for m in transport.sent} == {
        "Cheena FBR POS — Subscription expires in 4 days"
    }
    statuses = sorted((r.days_offset, r.status, r.cancel_reason) for r in rows(world))
    assert statuses == [
        (-6, "cancelled", "missed_send_window"),
        (-6, "cancelled", "missed_send_window"),
        (-4, "accepted", None),
        (-4, "accepted", None),
    ]


def test_retry_after_midnight_is_cancelled(world: Session, factory, at) -> None:
    world.execute(update(SubscriptionReminderSettings).values(notify_company_admin=False))
    world.commit()
    day = EXPIRY - timedelta(days=5)
    at(pkt(day, 23, 58))
    evaluate(factory)
    transport = ScriptedTransport(["smtp_timeout"])
    dispatch(factory, transport)
    at(pkt(day + timedelta(days=1), 0, 5))
    dispatch(factory, transport)
    row = rows(world)[0]
    assert row.status == "cancelled" and row.cancel_reason == "missed_send_window"
    assert transport.calls == 1


# --- Renewal -------------------------------------------------------------------


def test_renewal_cancels_queued_reminders(world: Session, factory, at) -> None:
    today = EXPIRY - timedelta(days=3)
    at(pkt(today))
    evaluate(factory)
    actor = world.scalar(select(User).where(User.access_category == AccessCategory.SUPER_ADMIN))
    assert actor is not None
    new_expiry = EXPIRY + timedelta(days=365)
    renew_subscription(
        world,
        actor=actor,
        new_expiry_date=new_expiry,
        expected_expiry_date=EXPIRY,
        idempotency_key=uuid.uuid4(),
        today=today,
    )
    assert {(r.status, r.cancel_reason) for r in rows(world)} == {
        ("cancelled_obsolete", "subscription_renewed")
    }
    transport = ScriptedTransport()
    dispatch(factory, transport)
    assert transport.sent == []
    # Recalculated from the new expiry date: nothing due today.
    assert evaluate(factory).result == "no_reminder_due"
    assert len(rows(world)) == 2  # history kept
    assert "reminder.jobs_cancelled_obsolete" in actions(world)


def test_expiry_change_detected_at_send_time(world: Session, factory, at) -> None:
    at(pkt(EXPIRY + timedelta(days=1)))
    evaluate(factory)
    # Expiry changed by another path that did not cancel the queue.
    world.execute(update(AppSubscription).values(expiry_date=EXPIRY + timedelta(days=30)))
    world.commit()
    transport = ScriptedTransport()
    dispatch(factory, transport)
    assert transport.sent == []
    assert {r.status for r in rows(world)} == {"cancelled_obsolete"}


def test_renewal_rolls_back_with_cancellation(
    world: Session, factory, at, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.subscription_renewal as renewal_module

    today = EXPIRY - timedelta(days=3)
    at(pkt(today))
    evaluate(factory)

    def boom(*args, **kwargs):
        raise RuntimeError("database failure during cancellation")

    monkeypatch.setattr(renewal_module, "cancel_obsolete", boom)
    actor = world.scalar(select(User).where(User.access_category == AccessCategory.SUPER_ADMIN))
    with pytest.raises(RuntimeError):
        renew_subscription(
            world,
            actor=actor,
            new_expiry_date=EXPIRY + timedelta(days=30),
            expected_expiry_date=EXPIRY,
            idempotency_key=uuid.uuid4(),
            today=today,
        )
    world.expire_all()
    assert world.get(AppSubscription, 1).expiry_date == EXPIRY  # renewal rolled back
    assert {r.status for r in rows(world)} == {"pending"}


def test_evaluation_rolls_back_on_error(
    world: Session, factory, at, monkeypatch: pytest.MonkeyPatch
) -> None:
    at(pkt(EXPIRY - timedelta(days=2)))
    original = outbox._audit

    def failing(db, actor, action, details):
        if action == "reminder.jobs_queued":
            raise RuntimeError("simulated failure")
        original(db, actor, action, details)

    monkeypatch.setattr(outbox, "_audit", failing)
    with pytest.raises(RuntimeError):
        evaluate(factory)
    assert rows(world) == []
    world.expire_all()
    assert world.get(SubscriptionReminderSettings, 1).last_run_at is None


# --- Templates, audit, secrets -------------------------------------------------


def test_template_escapes_html_and_has_plain_text() -> None:
    content = render_reminder(
        stage=ReminderStage(-2),
        company_name='<script>alert("x")</script> & Co',
        expiry_date=EXPIRY,
        status_label="Expiring Soon",
    )
    assert "<script>" not in content.html
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; Co" in content.html
    assert '<script>alert("x")</script> & Co' in content.text  # plain text is not HTML
    assert content.subject == "Cheena FBR POS — Subscription expires in 2 days"
    assert "20 Mar 2027" in content.text
    assert "http" not in content.text and "http" not in content.html.replace("https", "")


def test_expiry_day_and_after_templates() -> None:
    today = render_reminder(
        stage=ReminderStage(0), company_name="C", expiry_date=EXPIRY, status_label="Expiring Soon"
    )
    assert today.subject == "Cheena FBR POS — Subscription expires today"
    assert "last valid day" in today.text
    after = render_reminder(
        stage=ReminderStage(1), company_name="C", expiry_date=EXPIRY, status_label="Expired"
    )
    assert after.subject == "Cheena FBR POS — Subscription expired 1 day ago"
    assert "Company Workspace access is restricted" in after.text


def test_sent_message_structure(world: Session, factory, at) -> None:
    at(pkt(EXPIRY - timedelta(days=1)))
    evaluate(factory)
    transport = ScriptedTransport()
    dispatch(factory, transport)
    message = transport.sent[0]
    assert message["From"] == "Cheena POS <sender@example.com>"
    assert message["Auto-Submitted"] == "auto-generated"
    assert message.get_content_type() == "multipart/alternative"
    parts = [p.get_content_type() for p in message.iter_parts()]
    assert parts == ["text/plain", "text/html"]
    html = message.get_body(("html",)).get_content()
    assert "Cheena &amp; Sons &lt;Pvt&gt;" in html


def test_audit_trail_and_no_poll_noise(world: Session, factory, at) -> None:
    at(pkt(EXPIRY - timedelta(days=30)))
    for _ in range(4):
        evaluate(factory)
    assert actions(world).count("reminder.schedule_evaluated") == 1
    at(pkt(EXPIRY - timedelta(days=1)))
    evaluate(factory)
    evaluate(factory)
    dispatch(factory, ScriptedTransport(["smtp_timeout"]))
    trail = actions(world)
    assert trail.count("reminder.jobs_queued") == 1
    assert trail.count("reminder.delivery_attempted") == 2
    # no_reminder_due -> queued -> already_queued: one record per change of outcome.
    assert trail.count("reminder.schedule_evaluated") == 3
    for _ in range(3):
        evaluate(factory)
    assert actions(world).count("reminder.schedule_evaluated") == 3


def test_no_secrets_in_logs_or_audit(
    world: Session, factory, at, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    at(pkt(EXPIRY))
    evaluate(factory)
    dispatch(factory, ScriptedTransport(["smtp_auth_failed"]))
    from app.core.config import get_settings

    key = get_settings().email_settings_encryption_key or ""
    with factory() as db:
        audit_dump = " ".join(str(d) for d in db.scalars(select(AuditEvent.details)))
    for secret in (SMTP_PASSWORD, key):
        assert secret not in caplog.text
        assert secret not in audit_dump
    assert "owner@example.test" not in audit_dump  # recipients are masked


# --- Celery task bodies -------------------------------------------------------


def test_celery_tasks_run_the_pipeline(world: Session, at, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks import reminders as tasks

    transport = ScriptedTransport()
    monkeypatch.setattr(tasks, "get_smtp_transport", lambda: transport)
    monkeypatch.setattr(tasks.dispatch_email_outbox, "delay", lambda: tasks.dispatch_email_outbox())
    at(pkt(EXPIRY - timedelta(days=7)))
    assert tasks.evaluate_reminders() == {"result": "queued", "queued": 2}
    assert len(transport.sent) == 2
    assert tasks.dispatch_email_outbox()["handled"] == 0


def test_beat_schedule_is_configured() -> None:
    from app.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert schedule["reminders-evaluate"]["task"] == "reminders.evaluate"
    assert schedule["email-outbox-dispatch"]["task"] == "email_outbox.dispatch"
    assert celery_app.conf.task_acks_late is True


# --- API -------------------------------------------------------------------------


@pytest.fixture
def admin(client: TestClient, make_user) -> TestClient:
    email, password = make_user(AccessCategory.SUPER_ADMIN)
    assert login(client, email, password).status_code == 200
    return client


def put(client: TestClient, body: dict) -> object:
    return client.put(URL + "/reminders", json=body, headers={**csrf_header(client), **ORIGIN})


def test_api_requires_authentication(client: TestClient) -> None:
    assert client.get(URL + "/reminders").status_code == 401
    assert client.get(URL + "/reminder-history").status_code == 401
    assert client.put(URL + "/reminders", json={}).status_code == 401


@pytest.mark.usefixtures("valid_subscription")
@pytest.mark.parametrize("category", [AccessCategory.COMPANY_ADMIN, AccessCategory.COMPANY_USER])
def test_api_denies_company_accounts(client: TestClient, make_user, category) -> None:
    email, password = make_user(category)
    assert login(client, email, password).status_code == 200
    assert client.get(URL + "/reminders").status_code == 403
    assert client.get(URL + "/reminder-history").status_code == 403
    body = {
        "is_enabled": True,
        "notify_super_admin": True,
        "notify_company_admin": True,
        "expected_version": 1,
    }
    assert put(client, body).status_code == 403


def test_api_requires_csrf(admin: TestClient, db: Session) -> None:
    body = {
        "is_enabled": True,
        "notify_super_admin": True,
        "notify_company_admin": True,
        "expected_version": 1,
    }
    res = admin.put(URL + "/reminders", json=body, headers=ORIGIN)
    assert res.status_code == 403 and res.json()["error"]["code"] == "csrf_failed"
    res = admin.put(
        URL + "/reminders",
        json=body,
        headers={**csrf_header(admin), "Origin": "https://evil.example"},
    )
    assert res.status_code == 403
    db.expire_all()
    assert db.get(SubscriptionReminderSettings, 1).is_enabled is False


def test_api_defaults_and_update(admin: TestClient, db: Session) -> None:
    data = admin.get(URL + "/reminders").json()
    assert data["settings"]["is_enabled"] is False  # disabled by default
    assert data["schedule"]["days_before"] == 15 and data["schedule"]["days_after"] == 5
    assert data["schedule"]["timezone"] == "Asia/Karachi"
    assert data["readiness"] == {"email_configured": False, "email_enabled": False}
    version = data["settings"]["version"]
    res = put(
        admin,
        {
            "is_enabled": True,
            "notify_super_admin": True,
            "notify_company_admin": False,
            "expected_version": version,
        },
    )
    assert res.status_code == 200, res.text
    out = res.json()["settings"]
    assert out["is_enabled"] is True and out["notify_company_admin"] is False
    assert out["version"] == version + 1
    trail = actions(db)
    assert "reminder.enabled" in trail and "reminder.recipients_updated" in trail
    # Stale version
    res = put(
        admin,
        {
            "is_enabled": False,
            "notify_super_admin": True,
            "notify_company_admin": True,
            "expected_version": version,
        },
    )
    assert res.status_code == 409


def test_api_rejects_enabling_without_recipients(admin: TestClient) -> None:
    res = put(
        admin,
        {
            "is_enabled": True,
            "notify_super_admin": False,
            "notify_company_admin": False,
            "expected_version": 1,
        },
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "invalid_reminder_settings"


def test_api_masks_recipients_and_never_returns_secrets(
    world: Session, admin: TestClient, factory, at
) -> None:
    at(pkt(EXPIRY - timedelta(days=2)))
    evaluate(factory)
    dispatch(factory, ScriptedTransport(["smtp_recipient_refused"]))
    overview = admin.get(URL + "/reminders")
    history = admin.get(URL + "/reminder-history")
    for res in (overview, history):
        assert res.status_code == 200
        assert "admin@example.test" not in res.text
        assert SMTP_PASSWORD not in res.text
        assert "encrypted" not in res.text
    items = history.json()["items"]
    assert {i["recipient"] for i in items} >= {"ad***@example.test"}
    failed = [i for i in items if i["status"] == "failed_permanent"]
    assert failed and failed[0]["reason"] == "The SMTP server refused the recipient email address."


def test_api_history_filter_and_pagination(world: Session, admin: TestClient, factory, at) -> None:
    for i in range(4):
        add_user(world, AccessCategory.COMPANY_ADMIN, f"page{i}@example.test")
    at(pkt(EXPIRY - timedelta(days=2)))
    # The signed-in API account is a second Super Admin, so the Super Admin
    # recipient is ambiguous and skipped: 5 Company Admin rows, all pending.
    evaluate(factory)
    page = admin.get(URL + "/reminder-history?limit=4&offset=0").json()
    assert page["total"] == 5 and len(page["items"]) == 4
    page2 = admin.get(URL + "/reminder-history?limit=4&offset=4").json()
    assert len(page2["items"]) == 1
    assert admin.get(URL + "/reminder-history?status=accepted").json()["total"] == 0
    assert admin.get(URL + "/reminder-history?status=pending").json()["total"] == 5
    assert admin.get(URL + "/reminder-history?status=bogus").status_code == 422
    assert page["counts"]["pending"] == 5
    overview = admin.get(URL + "/reminders").json()
    assert overview["recipients"]["super_admin_status"] == "ambiguous"


def test_api_disabling_cancels_open_reminders(
    world: Session, admin: TestClient, factory, at
) -> None:
    at(pkt(EXPIRY - timedelta(days=2)))
    evaluate(factory)
    version = admin.get(URL + "/reminders").json()["settings"]["version"]
    res = put(
        admin,
        {
            "is_enabled": False,
            "notify_super_admin": True,
            "notify_company_admin": True,
            "expected_version": version,
        },
    )
    assert res.status_code == 200
    assert {(r.status, r.cancel_reason) for r in rows(world)} == {
        ("cancelled", "reminders_disabled")
    }
    assert "reminder.disabled" in actions(world)
    assert "reminder.jobs_cancelled" in actions(world)


def test_reminder_settings_do_not_touch_smtp_settings(world: Session, admin: TestClient) -> None:
    before = world.execute(text("SELECT row_to_json(e)::text FROM email_settings e")).scalar_one()
    version = admin.get(URL + "/reminders").json()["settings"]["version"]
    put(
        admin,
        {
            "is_enabled": False,
            "notify_super_admin": False,
            "notify_company_admin": True,
            "expected_version": version,
        },
    )
    after = world.execute(text("SELECT row_to_json(e)::text FROM email_settings e")).scalar_one()
    assert before == after


def test_next_reminder_day_moves_on_once_today_is_queued(
    world: Session, admin: TestClient, factory, at
) -> None:
    today = EXPIRY - timedelta(days=2)
    at(pkt(today, 8, 0))  # before send time: today is still upcoming
    assert admin.get(URL + "/reminders").json()["schedule"]["next_reminder_date"] == (
        today.isoformat()
    )
    at(pkt(today, 10, 0))
    evaluate(factory)
    data = admin.get(URL + "/reminders").json()["schedule"]
    assert data["next_reminder_date"] == (today + timedelta(days=1)).isoformat()
    at(pkt(EXPIRY + timedelta(days=5)))
    evaluate(factory)
    assert admin.get(URL + "/reminders").json()["schedule"]["next_reminder_date"] is None
