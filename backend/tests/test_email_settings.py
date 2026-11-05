"""Super Admin Email Settings API.

Every SMTP interaction goes through ``FakeTransport``; nothing here opens a
network connection or sends a real email.
"""

import logging
import secrets
import uuid
from email.message import EmailMessage

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core import secret_box
from app.core.config import get_settings
from app.core.redis import get_redis
from app.main import app
from app.models import AccessCategory, AuditEvent, EmailSettings
from app.services import email_settings as svc
from app.services.smtp_transport import SmtpConfig, failure, get_smtp_transport
from tests.conftest import csrf_header, login

URL = "/api/v1/super-admin/email-settings"
ORIGIN = {"Origin": "http://localhost:3000"}


class FakeTransport:
    def __init__(self) -> None:
        self.connections: list[SmtpConfig] = []
        self.sent: list[tuple[SmtpConfig, EmailMessage]] = []
        self.fail_with: str | None = None

    def check_connection(self, config: SmtpConfig) -> None:
        self.connections.append(config)
        if self.fail_with:
            raise failure(self.fail_with)

    def send(self, config: SmtpConfig, message: EmailMessage) -> None:
        self.sent.append((config, message))
        if self.fail_with:
            raise failure(self.fail_with)


@pytest.fixture
def fake() -> FakeTransport:
    transport = FakeTransport()
    app.dependency_overrides[get_smtp_transport] = lambda: transport
    return transport


@pytest.fixture
def admin(client: TestClient, make_user) -> TestClient:
    email, password = make_user(AccessCategory.SUPER_ADMIN)
    assert login(client, email, password).status_code == 200
    return client


def _app_password() -> str:
    return "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(16))


def payload(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "encryption_mode": "starttls",
        "smtp_username": "sender@example.com",
        "smtp_password": "s3cret-" + secrets.token_hex(8),
        "sender_email": "sender@example.com",
        "sender_name": "Cheena POS",
        "expected_version": None,
    }
    body.update(overrides)
    return body


def put(client: TestClient, body: dict[str, object]):
    return client.put(URL, json=body, headers={**csrf_header(client), **ORIGIN})


def post(client: TestClient, path: str, body: dict[str, object] | None = None):
    return client.post(URL + path, json=body or {}, headers={**csrf_header(client), **ORIGIN})


def configure(client: TestClient, enabled: bool = False, **overrides: object) -> dict:
    res = put(client, payload(**overrides))
    assert res.status_code == 200, res.text
    data = res.json()
    if enabled:
        res = client.put(
            URL + "/sending",
            json={"enabled": True, "expected_version": data["settings"]["version"]},
            headers={**csrf_header(client), **ORIGIN},
        )
        assert res.status_code == 200, res.text
        data = res.json()
    return data


def stored(db: Session) -> EmailSettings:
    db.expire_all()
    row = db.get(EmailSettings, 1)
    assert row is not None
    return row


def audits(db: Session, prefix: str = "email_settings.") -> list[AuditEvent]:
    db.expire_all()
    return list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.action.startswith(prefix))
            .order_by(AuditEvent.occurred_at, AuditEvent.id)
        )
    )


def send_test(client: TestClient, recipient: str = "inbox@example.com", key: str | None = None):
    return post(
        client,
        "/test-email",
        {"recipient_email": recipient, "idempotency_key": key or str(uuid.uuid4())},
    )


# --- Access control ----------------------------------------------------------


def test_unauthenticated_requests_get_401(client: TestClient) -> None:
    assert client.get(URL).status_code == 401
    assert client.put(URL, json=payload()).status_code == 401
    assert client.post(URL + "/test-connection").status_code == 401


@pytest.mark.usefixtures("valid_subscription")
@pytest.mark.parametrize("category", [AccessCategory.COMPANY_ADMIN, AccessCategory.COMPANY_USER])
def test_company_accounts_get_403(
    client: TestClient, make_user, fake: FakeTransport, category: AccessCategory
) -> None:
    email, password = make_user(category)
    assert login(client, email, password).status_code == 200
    assert client.get(URL).status_code == 403
    assert put(client, payload()).status_code == 403
    assert post(client, "/test-connection").status_code == 403
    assert send_test(client).status_code == 403
    sending = client.put(
        URL + "/sending",
        json={"enabled": True, "expected_version": 1},
        headers={**csrf_header(client), **ORIGIN},
    )
    assert sending.status_code == 403
    assert fake.connections == [] and fake.sent == []


def test_writes_require_csrf_token(admin: TestClient, fake: FakeTransport, db: Session) -> None:
    res = admin.put(URL, json=payload(), headers=ORIGIN)
    assert res.status_code == 403 and res.json()["error"]["code"] == "csrf_failed"
    res = admin.post(URL + "/test-connection", headers=ORIGIN)
    assert res.status_code == 403
    assert db.get(EmailSettings, 1) is None


def test_writes_reject_foreign_origin(admin: TestClient) -> None:
    res = admin.put(
        URL, json=payload(), headers={**csrf_header(admin), "Origin": "https://evil.example"}
    )
    assert res.status_code == 403 and res.json()["error"]["code"] == "csrf_failed"


# --- Reading and saving ------------------------------------------------------


def test_not_configured_state(admin: TestClient) -> None:
    data = admin.get(URL).json()
    assert data["status"] == "not_configured"
    assert data["settings"] is None and data["history"] is None
    assert data["encryption_ready"] is True
    assert data["allowed_ports"] == [25, 465, 587, 2525]


def test_create_encrypts_password_and_never_returns_it(
    admin: TestClient, db: Session, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    body = payload()
    password = str(body["smtp_password"])
    res = put(admin, body)
    assert res.status_code == 200
    assert password not in res.text
    data = res.json()
    assert data["status"] == "disabled"  # saved settings start with sending off
    assert data["settings"]["password_set"] is True
    assert data["settings"]["password_readable"] is True
    assert "smtp_password" not in data["settings"]
    assert "encrypted_smtp_password" not in data["settings"]

    row = stored(db)
    assert row.encrypted_smtp_password and row.encrypted_smtp_password.startswith("v1:")
    assert password not in row.encrypted_smtp_password
    assert secret_box.decrypt(row.encrypted_smtp_password, svc.PASSWORD_PURPOSE) == password

    # Not in the GET response, the audit log or any log record.
    assert password not in admin.get(URL).text
    events = audits(db)
    assert [e.action for e in events] == ["email_settings.created"]
    assert password not in str(events[0].details)
    assert row.encrypted_smtp_password not in str(events[0].details)
    assert password not in caplog.text


def test_ciphertext_is_not_stored_anywhere_in_plaintext(admin: TestClient, db: Session) -> None:
    body = payload()
    put(admin, body)
    dump = db.execute(text("SELECT row_to_json(e)::text FROM email_settings e")).scalar_one()
    assert str(body["smtp_password"]) not in dump


def test_blank_password_keeps_stored_password(admin: TestClient, db: Session) -> None:
    first = configure(admin)
    before = stored(db).encrypted_smtp_password
    res = put(
        admin,
        payload(
            smtp_password="",
            sender_name="Cheena Billing",
            expected_version=first["settings"]["version"],
        ),
    )
    assert res.status_code == 200, res.text
    row = stored(db)
    assert row.encrypted_smtp_password == before
    assert row.sender_name == "Cheena Billing"
    assert row.version == first["settings"]["version"] + 1
    update = audits(db)[-1]
    assert update.action == "email_settings.updated"
    assert update.details["changed_fields"] == ["sender_name"]
    assert update.details["password_changed"] is False


def test_omitted_password_keeps_stored_password(admin: TestClient, db: Session) -> None:
    first = configure(admin)
    before = stored(db).encrypted_smtp_password
    body = payload(expected_version=first["settings"]["version"], sender_name="Other")
    del body["smtp_password"]
    assert put(admin, body).status_code == 200
    assert stored(db).encrypted_smtp_password == before


def test_new_password_replaces_stored_password(admin: TestClient, db: Session) -> None:
    first = configure(admin)
    before = stored(db).encrypted_smtp_password
    res = put(
        admin,
        payload(smtp_password="brand-new-pass", expected_version=first["settings"]["version"]),
    )
    assert res.status_code == 200
    row = stored(db)
    assert row.encrypted_smtp_password != before
    assert secret_box.decrypt(row.encrypted_smtp_password or "", svc.PASSWORD_PURPOSE) == (
        "brand-new-pass"
    )
    assert audits(db)[-1].details["password_changed"] is True


def test_same_password_encrypts_differently_each_time() -> None:
    a = secret_box.encrypt("same", svc.PASSWORD_PURPOSE)
    b = secret_box.encrypt("same", svc.PASSWORD_PURPOSE)
    assert a != b  # random nonce


def test_gmail_app_password_spaces_are_removed(admin: TestClient, db: Session) -> None:
    app_password = _app_password()
    spaced = " ".join(app_password[i : i + 4] for i in range(0, 16, 4))
    configure(admin, smtp_host="smtp.gmail.com", smtp_password=spaced)
    row = stored(db)
    assert secret_box.decrypt(row.encrypted_smtp_password or "", svc.PASSWORD_PURPOSE) == (
        app_password
    )


def test_username_requires_password_on_create(admin: TestClient, db: Session) -> None:
    res = put(admin, payload(smtp_password=""))
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "invalid_email_settings"
    assert db.get(EmailSettings, 1) is None


def test_no_username_means_no_password(admin: TestClient, db: Session) -> None:
    first = configure(admin)
    res = put(
        admin,
        payload(smtp_username="", smtp_password="", expected_version=first["settings"]["version"]),
    )
    assert res.status_code == 200
    row = stored(db)
    assert row.smtp_username is None and row.encrypted_smtp_password is None
    assert res.json()["settings"]["password_set"] is False


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.10",
        "172.16.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "[::1]",
        "::ffff:127.0.0.1",
        "metadata.google.internal",
        "mail.local",
        "postgres",
        "redis",
        "smtp",
        "bad host.com",
        "-bad.example.com",
        "",
    ],
)
def test_unsafe_or_invalid_hosts_are_rejected(admin: TestClient, db: Session, host: str) -> None:
    res = put(admin, payload(smtp_host=host))
    assert res.status_code == 422, host
    assert db.get(EmailSettings, 1) is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"smtp_port": 8080},
        {"smtp_port": 22},
        {"smtp_port": 0},
        {"encryption_mode": "none"},
        {"sender_email": "not-an-email"},
        {"sender_email": "a@b.com\r\nBcc: victim@example.com"},
        {"sender_name": "Cheena\r\nBcc: victim@example.com"},
        {"sender_name": "   "},
        {"smtp_username": "user\nname"},
        {"smtp_password": "pass\r\nword"},
        {"smtp_password": "x" * 257},
    ],
)
def test_invalid_fields_are_rejected(
    admin: TestClient, db: Session, overrides: dict[str, object]
) -> None:
    res = put(admin, payload(**overrides))
    assert res.status_code == 422, overrides
    assert db.get(EmailSettings, 1) is None


def test_ssl_on_465_is_accepted(admin: TestClient) -> None:
    data = configure(admin, smtp_host="smtp.gmail.com", smtp_port=465, encryption_mode="ssl")
    assert data["settings"]["smtp_port"] == 465
    assert data["settings"]["encryption_mode"] == "ssl"


def test_stale_version_is_rejected(admin: TestClient, db: Session) -> None:
    first = configure(admin)
    version = first["settings"]["version"]
    assert put(admin, payload(sender_name="A", expected_version=version)).status_code == 200
    res = put(admin, payload(sender_name="B", expected_version=version))
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "stale_email_settings"
    assert stored(db).sender_name == "A"


def test_create_twice_is_rejected(admin: TestClient) -> None:
    configure(admin)
    res = put(admin, payload())
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "stale_email_settings"


def test_unchanged_save_is_a_no_op(admin: TestClient, db: Session) -> None:
    first = configure(admin)
    body = payload(smtp_password="", expected_version=first["settings"]["version"])
    res = put(admin, body)
    assert res.status_code == 200
    assert res.json()["settings"]["version"] == first["settings"]["version"]
    assert [e.action for e in audits(db)] == ["email_settings.created"]


# --- Enable / disable --------------------------------------------------------


def test_enable_and_disable_sending(admin: TestClient, db: Session) -> None:
    data = configure(admin)
    version = data["settings"]["version"]
    res = admin.put(
        URL + "/sending",
        json={"enabled": True, "expected_version": version},
        headers={**csrf_header(admin), **ORIGIN},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "configured"
    res = admin.put(
        URL + "/sending",
        json={"enabled": False, "expected_version": version + 1},
        headers={**csrf_header(admin), **ORIGIN},
    )
    assert res.json()["status"] == "disabled"
    assert [e.action for e in audits(db)] == [
        "email_settings.created",
        "email_settings.sending_enabled",
        "email_settings.sending_disabled",
    ]


def test_enable_requires_configuration(admin: TestClient) -> None:
    res = admin.put(
        URL + "/sending",
        json={"enabled": True, "expected_version": 1},
        headers={**csrf_header(admin), **ORIGIN},
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "email_not_configured"


def test_enable_with_stale_version_is_rejected(admin: TestClient) -> None:
    data = configure(admin)
    res = admin.put(
        URL + "/sending",
        json={"enabled": True, "expected_version": data["settings"]["version"] + 5},
        headers={**csrf_header(admin), **ORIGIN},
    )
    assert res.status_code == 409


# --- Test connection ---------------------------------------------------------


def test_connection_test_uses_saved_settings_and_sends_nothing(
    admin: TestClient, fake: FakeTransport, db: Session
) -> None:
    body = payload()
    configure(admin, smtp_password=body["smtp_password"])
    res = post(admin, "/test-connection")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["ok"] is True and data["kind"] == "connection"
    assert "No email was sent" in data["message"]
    assert fake.sent == []
    assert len(fake.connections) == 1
    config = fake.connections[0]
    assert config.host == "smtp.example.com" and config.port == 587
    assert config.mode == "starttls"
    assert config.password == body["smtp_password"]  # decrypted only in memory
    assert config.allow_private_hosts is False
    assert str(body["smtp_password"]) not in res.text

    history = data["email_settings"]["history"]
    assert history["last_test_status"] == "success"
    assert history["last_success_at"] is not None
    event = audits(db)[-1]
    assert event.action == "email_settings.connection_tested"
    assert event.details["result"] == "success"
    assert str(body["smtp_password"]) not in str(event.details)


def test_connection_test_works_while_sending_disabled(
    admin: TestClient, fake: FakeTransport
) -> None:
    assert configure(admin)["status"] == "disabled"
    assert post(admin, "/test-connection").json()["ok"] is True


def test_connection_test_failure_is_recorded_safely(
    admin: TestClient, fake: FakeTransport, db: Session
) -> None:
    configure(admin)
    fake.fail_with = "smtp_auth_failed"
    res = post(admin, "/test-connection")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is False and data["code"] == "smtp_auth_failed"
    assert "App Password" in data["message"]
    history = data["email_settings"]["history"]
    assert history["last_test_status"] == "failure"
    assert history["last_failure_code"] == "smtp_auth_failed"
    assert history["last_failure_at"] is not None
    assert history["last_success_at"] is None
    assert audits(db)[-1].details["error_code"] == "smtp_auth_failed"


def test_connection_test_requires_configuration(admin: TestClient, fake: FakeTransport) -> None:
    res = post(admin, "/test-connection")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "email_not_configured"
    assert fake.connections == []


def test_unexpected_transport_error_is_generic(
    admin: TestClient, fake: FakeTransport, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(admin)

    def boom(config: SmtpConfig) -> None:
        raise RuntimeError("internal detail: password=hunter2")

    monkeypatch.setattr(fake, "check_connection", boom)
    res = post(admin, "/test-connection")
    assert res.status_code == 200
    assert res.json()["code"] == "smtp_error"
    assert "hunter2" not in res.text


def test_changing_connection_fields_resets_test_history(
    admin: TestClient, fake: FakeTransport, db: Session
) -> None:
    configure(admin)
    post(admin, "/test-connection")
    version = stored(db).version
    put(admin, payload(smtp_host="smtp.gmail.com", smtp_password="", expected_version=version))
    row = stored(db)
    assert row.last_test_status is None and row.last_success_at is None


def test_changing_sender_name_keeps_test_history(
    admin: TestClient, fake: FakeTransport, db: Session
) -> None:
    configure(admin)
    post(admin, "/test-connection")
    version = stored(db).version
    put(admin, payload(sender_name="New name", smtp_password="", expected_version=version))
    assert stored(db).last_test_status == "success"


# --- Test email --------------------------------------------------------------


def test_test_email_requires_sending_enabled(
    admin: TestClient, fake: FakeTransport, db: Session
) -> None:
    configure(admin, enabled=False)
    res = send_test(admin)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "email_sending_disabled"
    assert fake.sent == []


def test_test_email_requires_configuration(admin: TestClient, fake: FakeTransport) -> None:
    res = send_test(admin)
    assert res.status_code == 409
    assert fake.sent == []


def test_test_email_is_sent_through_transport(
    admin: TestClient, fake: FakeTransport, db: Session
) -> None:
    configure(admin, enabled=True)
    res = send_test(admin, recipient="Inbox@Example.com")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["ok"] is True and data["kind"] == "email"
    assert data["message"] == (
        "Test email accepted by the SMTP server. Please check the recipient inbox."
    )
    assert len(fake.sent) == 1
    _, message = fake.sent[0]
    assert message["To"] == "inbox@example.com"
    assert message["From"] == "Cheena POS <sender@example.com>"
    assert message["Subject"] == "Cheena FBR POS Software: test email"
    assert message["Message-ID"]
    assert "test email from Cheena FBR POS Software" in message.get_content()

    event = audits(db)[-1]
    assert event.action == "email_settings.test_email_sent"
    assert event.details["result"] == "success"
    assert event.details["recipient"] == "in***@example.com"  # masked
    assert data["email_settings"]["history"]["last_test_kind"] == "email"


def test_test_email_failure_is_reported(admin: TestClient, fake: FakeTransport) -> None:
    configure(admin, enabled=True)
    fake.fail_with = "smtp_recipient_refused"
    data = send_test(admin).json()
    assert data["ok"] is False
    assert data["code"] == "smtp_recipient_refused"
    assert data["email_settings"]["history"]["last_failure_code"] == "smtp_recipient_refused"


def test_test_email_rejects_invalid_recipient(admin: TestClient, fake: FakeTransport) -> None:
    configure(admin, enabled=True)
    for bad in ["nope", "a@b.com\r\nBcc: x@example.com", ""]:
        assert send_test(admin, recipient=bad).status_code == 422
    assert fake.sent == []


def test_duplicate_test_email_request_sends_once(
    admin: TestClient, fake: FakeTransport, db: Session
) -> None:
    configure(admin, enabled=True)
    key = str(uuid.uuid4())
    first = send_test(admin, key=key).json()
    second = send_test(admin, key=key).json()
    assert len(fake.sent) == 1
    assert first["replayed"] is False and second["replayed"] is True
    assert second["ok"] is True and second["tested_at"] == first["tested_at"]
    assert len(audits(db, "email_settings.test_email_sent")) == 1


def test_test_email_rate_limit(admin: TestClient, fake: FakeTransport) -> None:
    configure(admin, enabled=True)
    limit = get_settings().test_email_max_per_window
    for _ in range(limit):
        assert send_test(admin).status_code == 200
    res = send_test(admin)
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "rate_limited"
    assert int(res.headers["Retry-After"]) > 0
    assert len(fake.sent) == limit


def test_connection_test_rate_limit(admin: TestClient, fake: FakeTransport) -> None:
    configure(admin)
    for _ in range(svc.CONNECTION_TESTS_PER_WINDOW):
        assert post(admin, "/test-connection").status_code == 200
    assert post(admin, "/test-connection").status_code == 429


def test_concurrent_test_is_rejected(admin: TestClient, fake: FakeTransport) -> None:
    configure(admin, enabled=True)
    get_redis().set("lock:email_settings:test", "someone-else", ex=60)
    res = send_test(admin)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "email_test_in_progress"
    assert post(admin, "/test-connection").status_code == 409
    assert fake.sent == [] and fake.connections == []
    # Our release never removes another holder's lock.
    assert get_redis().get("lock:email_settings:test") == b"someone-else"


def test_lock_is_released_after_test(admin: TestClient, fake: FakeTransport) -> None:
    configure(admin, enabled=True)
    fake.fail_with = "smtp_timeout"
    send_test(admin)
    assert get_redis().get("lock:email_settings:test") is None


def test_redis_unavailable_fails_closed(admin: TestClient, fake: FakeTransport) -> None:
    configure(admin, enabled=True)
    broken = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)
    app.dependency_overrides[get_redis] = lambda: broken
    assert send_test(admin).status_code == 503
    assert post(admin, "/test-connection").status_code == 503
    assert fake.sent == [] and fake.connections == []


# --- Encryption key handling -------------------------------------------------


def test_missing_key_fails_securely(
    admin: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "email_settings_encryption_key", None)
    assert admin.get(URL).json()["encryption_ready"] is False
    res = put(admin, payload())
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "encryption_key_missing"
    assert "EMAIL_SETTINGS_ENCRYPTION_KEY" in res.json()["error"]["message"]
    assert db.get(EmailSettings, 1) is None


def test_invalid_key_fails_securely(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "email_settings_encryption_key", "too-short")
    with pytest.raises(secret_box.EncryptionKeyError):
        secret_box.encrypt("x", svc.PASSWORD_PURPOSE)
    assert secret_box.encryption_available() is False


def test_missing_key_blocks_tests_with_stored_password(
    admin: TestClient, fake: FakeTransport, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(admin)
    monkeypatch.setattr(get_settings(), "email_settings_encryption_key", "")
    res = post(admin, "/test-connection")
    assert res.status_code == 503
    assert fake.connections == []


def _new_key() -> str:
    import base64

    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def test_key_rotation_with_previous_keys(
    admin: TestClient, fake: FakeTransport, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = payload()
    configure(admin, smtp_password=body["smtp_password"])
    old_key = get_settings().email_settings_encryption_key
    old_token = stored(db).encrypted_smtp_password or ""
    monkeypatch.setattr(get_settings(), "email_settings_encryption_key", _new_key())
    monkeypatch.setattr(get_settings(), "email_settings_previous_keys", old_key)

    assert secret_box.needs_reencryption(old_token) is True
    assert admin.get(URL).json()["settings"]["password_readable"] is True
    assert post(admin, "/test-connection").json()["ok"] is True
    assert fake.connections[-1].password == body["smtp_password"]


def test_unknown_key_makes_password_unreadable(
    admin: TestClient, fake: FakeTransport, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(admin, enabled=True)
    monkeypatch.setattr(get_settings(), "email_settings_encryption_key", _new_key())
    data = admin.get(URL).json()
    assert data["settings"]["password_readable"] is False
    res = post(admin, "/test-connection")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "stored_password_unreadable"
    assert send_test(admin).status_code == 409
    # Saving without a new password is refused; re-entering one fixes it.
    version = data["settings"]["version"]
    blank = put(admin, payload(smtp_password="", sender_name="X", expected_version=version))
    assert blank.status_code == 409
    fixed = put(admin, payload(smtp_password="re-entered-pass", expected_version=version))
    assert fixed.status_code == 200
    assert fixed.json()["settings"]["password_readable"] is True
    assert fake.connections == [] and fake.sent == []


def test_tampered_ciphertext_is_rejected() -> None:
    token = secret_box.encrypt("secret-value", svc.PASSWORD_PURPOSE)
    version, key_id, blob = token.split(":", 2)
    flipped = blob[:-2] + ("A" if blob[-2] != "A" else "B") + blob[-1]
    with pytest.raises(secret_box.DecryptionError):
        secret_box.decrypt(f"{version}:{key_id}:{flipped}", svc.PASSWORD_PURPOSE)
    with pytest.raises(secret_box.DecryptionError):
        secret_box.decrypt(token, "some.other.purpose")
    with pytest.raises(secret_box.DecryptionError):
        secret_box.decrypt("garbage", svc.PASSWORD_PURPOSE)


def test_key_is_never_stored_in_database(admin: TestClient, db: Session) -> None:
    configure(admin)
    key = get_settings().email_settings_encryption_key or ""
    dump = db.execute(text("SELECT row_to_json(e)::text FROM email_settings e")).scalar_one()
    assert key and key not in dump
    audit_dump = " ".join(str(e.details) for e in audits(db))
    assert key not in audit_dump


def test_production_forbids_private_smtp_hosts() -> None:
    from app.core.config import Settings

    with pytest.raises(ValueError):
        Settings(
            database_url="postgresql+psycopg://x/y",
            environment="production",
            cookie_secure=True,
            smtp_allow_private_hosts=True,
        )
