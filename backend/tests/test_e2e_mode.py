"""Safety of the QA-only end-to-end switches (simulated clock, SMTP fault injection)."""

import os
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path

import pytest
from celery.schedules import crontab

from app.core import clock
from app.core.config import Settings, get_settings
from app.core.redis import get_redis
from app.services import smtp_transport as st
from app.services.smtp_transport import SINK_FAULTS_KEY, SinkTransport, SmtpConfig, SmtpFailure

CONFIG = SmtpConfig("smtp.example.com", 587, "starttls", None, None, 1.0)


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+psycopg://u:p@postgres:5432/cheena_database_e2e",
        "environment": "development",
        "cookie_secure": False,
        "email_transport": "sink",
        "e2e_test_mode": True,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_e2e_mode_is_off_by_default() -> None:
    assert get_settings().e2e_test_mode is False
    get_redis().set(clock.SIMULATED_CLOCK_KEY, "2030-01-01T00:00:00+00:00")
    # Ignored unless E2E mode is on: the real clock is used.
    assert clock.utcnow().year < 2030
    with pytest.raises(RuntimeError):
        clock.set_simulated_now(datetime(2030, 1, 1, tzinfo=UTC))


def test_e2e_mode_accepts_only_a_disposable_e2e_database() -> None:
    assert settings().e2e_test_mode is True
    for name in ("cheena_database", "cheena_database_test", "cheena_database_e2e_backup"):
        with pytest.raises(ValueError, match="_e2e"):
            settings(database_url=f"postgresql+psycopg://u:p@postgres:5432/{name}")


def test_e2e_mode_refused_in_production_and_without_sink() -> None:
    with pytest.raises(ValueError):
        settings(environment="production", cookie_secure=True)
    with pytest.raises(ValueError, match="sink"):
        settings(email_transport="smtp")


def test_simulated_clock_drives_application_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "e2e_test_mode", True)
    moment = datetime(2027, 3, 5, 5, 0, tzinfo=UTC)
    clock.set_simulated_now(moment)
    assert clock.utcnow() == moment
    get_redis().delete(clock.SIMULATED_CLOCK_KEY)
    assert abs((clock.utcnow() - datetime.now(UTC)).total_seconds()) < 5
    with pytest.raises(ValueError):
        clock.set_simulated_now(datetime(2027, 3, 5))  # naive


def test_sink_fault_injection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sink = SinkTransport(str(tmp_path), fault_injection=True)
    redis = get_redis()
    redis.rpush(SINK_FAULTS_KEY, "smtp_timeout", "smtp_auth_failed")
    message = EmailMessage()
    message["To"] = "x@example.test"
    message.set_content("hi")
    with pytest.raises(SmtpFailure) as transient:
        sink.send(CONFIG, message)
    assert transient.value.transient is True
    with pytest.raises(SmtpFailure) as permanent:
        sink.send(CONFIG, message)
    assert permanent.value.transient is False
    assert list(tmp_path.glob("*.eml")) == []
    sink.send(CONFIG, message)  # queue empty: delivered
    assert len(list(tmp_path.glob("*.eml"))) == 1

    exits: list[int] = []

    def fake_exit(code: int) -> None:
        exits.append(code)
        raise SystemExit(code)

    monkeypatch.setattr(os, "_exit", fake_exit)
    redis.rpush(SINK_FAULTS_KEY, "crash_before_accept", "crash_after_accept")
    with pytest.raises(SystemExit):
        sink.send(CONFIG, message)
    assert len(list(tmp_path.glob("*.eml"))) == 1  # nothing written before the crash
    with pytest.raises(SystemExit):
        sink.send(CONFIG, message)
    assert len(list(tmp_path.glob("*.eml"))) == 2  # written, then the crash
    assert exits == [st.CRASH_EXIT_CODE, st.CRASH_EXIT_CODE]


def test_sink_without_e2e_mode_ignores_fault_queue(tmp_path: Path) -> None:
    get_redis().rpush(SINK_FAULTS_KEY, "smtp_timeout")
    message = EmailMessage()
    message.set_content("hi")
    SinkTransport(str(tmp_path)).send(CONFIG, message)
    assert len(list(tmp_path.glob("*.eml"))) == 1


def test_default_beat_schedule_is_unchanged() -> None:
    from app.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert schedule["reminders-evaluate"]["schedule"] == crontab(minute="5,35")
    assert schedule["email-outbox-dispatch"]["schedule"] == 60.0
