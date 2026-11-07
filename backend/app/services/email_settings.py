"""Super Admin email (SMTP) settings: save, enable/disable and test.

Secrets:
- The SMTP password is encrypted with AES-256-GCM (``app.core.secret_box``)
  before it reaches the database and is decrypted only in memory, right before
  an SMTP login. It is never returned, logged or written to audit details.
- Saving with a blank password keeps the stored one.

Consistency:
- The single settings row is locked (``SELECT ... FOR UPDATE``) for writes and
  the caller's ``expected_version`` must match, so concurrent edits from two
  tabs are rejected (409) rather than silently overwritten.
- Network I/O (SMTP tests) never runs while the row lock is held. The result is
  recorded afterwards and only if the configuration was not changed meanwhile.

Tests (connection / test email):
- One test at a time (Redis lock), a per-admin rate limit per kind, and a
  client idempotency key for test emails so a double click or retry replays
  the first result instead of sending a second message. Redis failures fail
  closed (503): no SMTP traffic without the limiter.
- The SMTP client enforces TLS and the SSRF policy (``smtp_transport``).
"""

import json
import logging
import secrets
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from typing import cast

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import clock, secret_box
from app.core.config import get_settings
from app.core.dates import display_datetime
from app.core.errors import AppError
from app.core.security import is_valid_email, mask_email, normalize_email
from app.models import AuditEvent, EmailSettings, User
from app.models.email_settings import SINGLETON_ID
from app.services.smtp_transport import (
    ALLOWED_PORTS,
    FAILURE_MESSAGES,
    SmtpConfig,
    SmtpFailure,
    SmtpTransport,
    host_syntax_problem,
    normalize_host,
)

logger = logging.getLogger(__name__)

PASSWORD_PURPOSE = "email_settings.smtp_password"
ENCRYPTION_MODES = ("starttls", "ssl")
PASSWORD_MAX_LENGTH = 256
SENDER_NAME_MAX_LENGTH = 100
USERNAME_MAX_LENGTH = 320

STATUS_NOT_CONFIGURED = "not_configured"
STATUS_CONFIGURED = "configured"
STATUS_DISABLED = "disabled"

KIND_CONNECTION = "connection"
KIND_EMAIL = "email"

CONNECTION_OK_MESSAGE = (
    "Connection successful. The SMTP server accepted the secure connection{auth}. "
    "No email was sent."
)
EMAIL_OK_MESSAGE = "Test email accepted by the SMTP server. Please check the recipient inbox."
TEST_EMAIL_SUBJECT = "Cheena FBR POS Software: test email"

_CONNECTION_FIELDS = ("smtp_host", "smtp_port", "encryption_mode", "smtp_username")
_LOCK_KEY = "lock:email_settings:test"
_LOCK_TTL_SECONDS = 120
_IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60
CONNECTION_TESTS_PER_WINDOW = 10


@dataclass(frozen=True)
class SettingsInput:
    smtp_host: str
    smtp_port: int
    encryption_mode: str
    smtp_username: str | None
    smtp_password: str | None  # None / "" keeps the stored password
    sender_email: str
    sender_name: str
    expected_version: int | None


@dataclass(frozen=True)
class CheckOutcome:
    kind: str
    ok: bool
    code: str | None
    message: str
    tested_at: datetime
    replayed: bool = False


# --- Errors ------------------------------------------------------------------


def _invalid(message: str) -> AppError:
    return AppError(422, "invalid_email_settings", message)


def _stale() -> AppError:
    return AppError(
        409,
        "stale_email_settings",
        "The email settings were changed after this page was opened. Reload and try again.",
    )


def _not_configured() -> AppError:
    return AppError(409, "email_not_configured", "Save the SMTP settings first.")


def _encryption_unavailable() -> AppError:
    return AppError(
        503,
        "encryption_key_missing",
        "Email settings encryption is not set up on the server. An administrator must set "
        "EMAIL_SETTINGS_ENCRYPTION_KEY (see the README) and restart the backend.",
    )


def _password_unreadable() -> AppError:
    return AppError(
        409,
        "stored_password_unreadable",
        "The saved SMTP password can no longer be decrypted because the encryption key "
        "changed. Re-enter the SMTP password and save.",
    )


def _limiter_unavailable() -> AppError:
    return AppError(
        503, "service_unavailable", "Email testing is temporarily unavailable. Try again shortly."
    )


# --- Reading -----------------------------------------------------------------


def get_email_settings(db: Session) -> EmailSettings | None:
    return db.get(EmailSettings, SINGLETON_ID)


def status_of(row: EmailSettings | None) -> str:
    if row is None:
        return STATUS_NOT_CONFIGURED
    return STATUS_CONFIGURED if row.is_enabled else STATUS_DISABLED


def password_readable(row: EmailSettings) -> bool:
    if row.encrypted_smtp_password is None:
        return True
    return secret_box.key_available_for(row.encrypted_smtp_password)


def failure_message(code: str | None) -> str | None:
    if code is None:
        return None
    return FAILURE_MESSAGES.get(code, FAILURE_MESSAGES["smtp_error"])


# --- Validation --------------------------------------------------------------


def _has_control_chars(value: str) -> bool:
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


def _clean_host(raw: str) -> str:
    host = normalize_host(raw)
    problem = host_syntax_problem(host)
    if problem is None:
        return host
    allowed_private = get_settings().smtp_allow_private_hosts
    if allowed_private and problem == FAILURE_MESSAGES["smtp_host_not_allowed"]:
        return host
    raise _invalid(problem)


def _clean_password(raw: str | None, host: str) -> str | None:
    if raw is None or raw == "":
        return None
    if len(raw) > PASSWORD_MAX_LENGTH:
        raise _invalid(f"The SMTP password must be at most {PASSWORD_MAX_LENGTH} characters.")
    if _has_control_chars(raw):
        raise _invalid("The SMTP password contains characters that are not allowed.")
    # Google shows App Passwords as four groups of four letters; it expects
    # them without the spaces.
    if host == "smtp.gmail.com":
        compact = raw.replace(" ", "")
        if len(compact) == 16 and compact.isalpha():
            return compact
    if raw.strip() == "":
        raise _invalid("The SMTP password cannot be only spaces.")
    return raw


def _clean_input(data: SettingsInput) -> dict[str, object]:
    host = _clean_host(data.smtp_host)
    if data.smtp_port not in ALLOWED_PORTS:
        raise _invalid("Use port 587 (STARTTLS) or 465 (SSL/TLS). Ports 25 and 2525 also work.")
    if data.encryption_mode not in ENCRYPTION_MODES:
        raise _invalid("Choose STARTTLS or SSL/TLS.")
    username = (data.smtp_username or "").strip() or None
    if username is not None and (
        len(username) > USERNAME_MAX_LENGTH or _has_control_chars(username)
    ):
        raise _invalid("The SMTP username is not valid.")
    sender_email = normalize_email(data.sender_email)
    if not is_valid_email(sender_email) or _has_control_chars(sender_email):
        raise _invalid("Enter a valid sender email address.")
    # Reject control characters (CR/LF header injection) before normalizing spaces.
    if _has_control_chars(data.sender_name):
        raise _invalid("The sender name contains characters that are not allowed.")
    sender_name = " ".join(data.sender_name.split())
    if not sender_name:
        raise _invalid("Enter the sender name.")
    if len(sender_name) > SENDER_NAME_MAX_LENGTH:
        raise _invalid(f"The sender name must be at most {SENDER_NAME_MAX_LENGTH} characters.")
    if _has_control_chars(sender_name):
        raise _invalid("The sender name contains characters that are not allowed.")
    return {
        "smtp_host": host,
        "smtp_port": data.smtp_port,
        "encryption_mode": data.encryption_mode,
        "smtp_username": username,
        "sender_email": sender_email,
        "sender_name": sender_name,
        "password": _clean_password(data.smtp_password, host),
    }


# --- Writing -----------------------------------------------------------------


def _locked_row(db: Session) -> EmailSettings | None:
    return db.scalar(
        select(EmailSettings).where(EmailSettings.id == SINGLETON_ID).with_for_update()
    )


def _audit(db: Session, actor: User, action: str, details: dict[str, object]) -> None:
    db.add(AuditEvent(action=action, actor=f"user:{actor.id}", details=details))


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _stale() from None
    except Exception:
        db.rollback()
        raise


def save_settings(db: Session, *, actor: User, data: SettingsInput) -> EmailSettings:
    clean = _clean_input(data)
    new_password = clean.pop("password")
    encrypted: str | None = None
    if new_password is not None:
        try:
            encrypted = secret_box.encrypt(str(new_password), PASSWORD_PURPOSE)
        except secret_box.EncryptionKeyError:
            logger.error("email settings: encryption key missing or invalid")
            raise _encryption_unavailable() from None

    row = _locked_row(db)
    if row is None:
        if data.expected_version is not None:
            db.rollback()
            raise _stale()
        if clean["smtp_username"] is not None and encrypted is None:
            db.rollback()
            raise _invalid("Enter the SMTP password.")
        row = EmailSettings(id=SINGLETON_ID, version=1, updated_by_user_id=actor.id, **clean)
        row.encrypted_smtp_password = encrypted
        db.add(row)
        db.flush()
        _audit(
            db,
            actor,
            "email_settings.created",
            {
                "smtp_host": row.smtp_host,
                "smtp_port": row.smtp_port,
                "encryption_mode": row.encryption_mode,
                "authentication": row.smtp_username is not None,
                "password_set": encrypted is not None,
                "sending_enabled": False,
            },
        )
        _commit(db)
        logger.info("email settings created by %s", actor.id)
        return row

    if data.expected_version != row.version:
        db.rollback()
        raise _stale()

    changed = [name for name, value in clean.items() if getattr(row, name) != value]
    password_changed = False
    if clean["smtp_username"] is None:
        password_changed = row.encrypted_smtp_password is not None
        row.encrypted_smtp_password = None
    elif encrypted is not None:
        row.encrypted_smtp_password = encrypted
        password_changed = True
    elif row.encrypted_smtp_password is None:
        db.rollback()
        raise _invalid("Enter the SMTP password.")
    elif not password_readable(row):
        db.rollback()
        raise _password_unreadable()

    if not changed and not password_changed:
        db.rollback()
        return row

    for name, value in clean.items():
        setattr(row, name, value)
    if password_changed or any(name in _CONNECTION_FIELDS for name in changed):
        # Earlier results describe a different connection; don't show them as current.
        _reset_test_results(row)
    row.version += 1
    row.updated_by_user_id = actor.id
    _audit(
        db,
        actor,
        "email_settings.updated",
        {
            "changed_fields": changed,
            "password_changed": password_changed,
            "smtp_host": row.smtp_host,
            "smtp_port": row.smtp_port,
            "encryption_mode": row.encryption_mode,
            "version": row.version,
        },
    )
    _commit(db)
    logger.info("email settings updated by %s (fields=%s)", actor.id, changed)
    return row


def _reset_test_results(row: EmailSettings) -> None:
    row.last_test_status = None
    row.last_test_kind = None
    row.last_test_at = None
    row.last_success_at = None
    row.last_failure_at = None
    row.last_failure_code = None


def set_sending_enabled(
    db: Session, *, actor: User, enabled: bool, expected_version: int
) -> EmailSettings:
    row = _locked_row(db)
    if row is None:
        db.rollback()
        raise _not_configured()
    if row.version != expected_version:
        db.rollback()
        raise _stale()
    if row.is_enabled == enabled:
        db.rollback()
        return row
    row.is_enabled = enabled
    row.version += 1
    row.updated_by_user_id = actor.id
    _audit(
        db,
        actor,
        "email_settings.sending_enabled" if enabled else "email_settings.sending_disabled",
        {"version": row.version},
    )
    _commit(db)
    logger.info("email sending %s by %s", "enabled" if enabled else "disabled", actor.id)
    return row


# --- Testing -----------------------------------------------------------------


class _TestGuard:
    """Redis lock (one test at a time) + per-admin fixed-window rate limit."""

    _RELEASE = (
        "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) "
        "else return 0 end"
    )

    def __init__(self, redis: Redis, actor: User, kind: str) -> None:
        self.redis = redis
        self.actor = actor
        self.kind = kind
        self.token = secrets.token_hex(16)
        self.held = False

    def acquire(self) -> None:
        try:
            self.held = bool(self.redis.set(_LOCK_KEY, self.token, nx=True, ex=_LOCK_TTL_SECONDS))
        except RedisError:
            logger.exception("email test lock unavailable")
            raise _limiter_unavailable() from None
        if not self.held:
            raise AppError(
                409,
                "email_test_in_progress",
                "Another email test is already running. Wait for it to finish.",
            )

    def count(self) -> None:
        settings = get_settings()
        window = settings.test_email_rate_window_seconds
        limit = (
            settings.test_email_max_per_window
            if self.kind == KIND_EMAIL
            else CONNECTION_TESTS_PER_WINDOW
        )
        key = f"rl:email_test:{self.kind}:{self.actor.id}"
        try:
            pipe = self.redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, window, nx=True)
            pipe.ttl(key)
            count, _, ttl = pipe.execute()
        except RedisError:
            logger.exception("email test rate limiter unavailable")
            raise _limiter_unavailable() from None
        if int(count) > limit:
            what = "test emails" if self.kind == KIND_EMAIL else "connection tests"
            raise AppError(
                429,
                "rate_limited",
                f"Too many {what}. Please wait and try again later.",
                headers={"Retry-After": str(max(int(ttl), 1))},
            )

    def release(self) -> None:
        if not self.held:
            return
        try:
            self.redis.eval(self._RELEASE, 1, _LOCK_KEY, self.token)
        except RedisError:
            logger.exception("email test lock release failed (expires on its own)")
        self.held = False


def load_smtp_config(row: EmailSettings) -> SmtpConfig:
    """SMTP connection settings with the password decrypted in memory only.

    Raises ``AppError`` (encryption_key_missing / stored_password_unreadable /
    invalid_email_settings) when the stored configuration cannot be used.
    """
    return _smtp_config(row)


def _smtp_config(row: EmailSettings) -> SmtpConfig:
    password: str | None = None
    if row.smtp_username is not None:
        if row.encrypted_smtp_password is None:
            raise _invalid("Enter the SMTP password and save before testing.")
        try:
            password = secret_box.decrypt(row.encrypted_smtp_password, PASSWORD_PURPOSE)
        except secret_box.EncryptionKeyError:
            logger.error("email settings: encryption key missing or invalid")
            raise _encryption_unavailable() from None
        except secret_box.DecryptionError:
            logger.error("email settings: stored SMTP password could not be decrypted")
            raise _password_unreadable() from None
    settings = get_settings()
    return SmtpConfig(
        host=row.smtp_host,
        port=row.smtp_port,
        mode=row.encryption_mode,
        username=row.smtp_username,
        password=password,
        timeout=settings.smtp_timeout_seconds,
        allow_private_hosts=settings.smtp_allow_private_hosts,
    )


def _record_result(
    db: Session,
    *,
    actor: User,
    tested_version: int,
    outcome: CheckOutcome,
    extra: dict[str, object],
) -> None:
    row = _locked_row(db)
    current = row is not None and row.version == tested_version
    if row is not None and current:
        row.last_test_status = "success" if outcome.ok else "failure"
        row.last_test_kind = outcome.kind
        row.last_test_at = outcome.tested_at
        if outcome.ok:
            row.last_success_at = outcome.tested_at
        else:
            row.last_failure_at = outcome.tested_at
            row.last_failure_code = outcome.code
    action = (
        "email_settings.connection_tested"
        if outcome.kind == KIND_CONNECTION
        else "email_settings.test_email_sent"
    )
    _audit(
        db,
        actor,
        action,
        {
            "result": "success" if outcome.ok else "failure",
            "error_code": outcome.code,
            "settings_version": tested_version,
            "settings_changed_during_test": not current,
            **extra,
        },
    )
    db.commit()


def _run(transport_call: Callable[[], None]) -> tuple[bool, str | None]:
    try:
        transport_call()
    except SmtpFailure as exc:
        return False, exc.code
    except Exception:
        # A transport bug must not leak details; report a generic SMTP failure.
        logger.exception("unexpected SMTP transport error")
        return False, "smtp_error"
    return True, None


def run_connection_test(
    db: Session, *, actor: User, transport: SmtpTransport, redis: Redis
) -> CheckOutcome:
    """Connect, secure and authenticate with the saved settings. Sends no email."""
    row = get_email_settings(db)
    if row is None:
        raise _not_configured()
    config = _smtp_config(row)
    tested_version = row.version
    db.rollback()  # end the read transaction before network I/O

    guard = _TestGuard(redis, actor, KIND_CONNECTION)
    guard.acquire()
    try:
        guard.count()
        ok, code = _run(lambda: transport.check_connection(config))
        message = (
            CONNECTION_OK_MESSAGE.format(auth=" and sign-in" if config.username else "")
            if ok
            else (failure_message(code) or "")
        )
        outcome = CheckOutcome(KIND_CONNECTION, ok, code, message, clock.utcnow())
        _record_result(db, actor=actor, tested_version=tested_version, outcome=outcome, extra={})
    finally:
        guard.release()
    logger.info("smtp connection test by %s: %s", actor.id, code or "ok")
    return outcome


def _idempotency_key(actor: User, key: uuid.UUID) -> str:
    return f"email_test:idem:{actor.id}:{key}"


def _load_replay(redis: Redis, key: str) -> CheckOutcome | None:
    try:
        raw = redis.get(key)
    except RedisError:
        logger.exception("email test idempotency store unavailable")
        raise _limiter_unavailable() from None
    if raw is None:
        return None
    data = json.loads(cast(bytes, raw))
    data["tested_at"] = datetime.fromisoformat(data["tested_at"])
    data["replayed"] = True
    return CheckOutcome(**data)


def _store_replay(redis: Redis, key: str, outcome: CheckOutcome) -> None:
    data = asdict(outcome)
    data["tested_at"] = outcome.tested_at.isoformat()
    try:
        redis.set(key, json.dumps(data), ex=_IDEMPOTENCY_TTL_SECONDS)
    except RedisError:
        logger.exception("email test idempotency store unavailable")


def build_test_message(row: EmailSettings, recipient: str, now: datetime) -> EmailMessage:
    try:
        sender = Address(display_name=row.sender_name, addr_spec=row.sender_email)
        to = Address(addr_spec=recipient)
    except (ValueError, IndexError):
        raise _invalid("The sender or recipient email address is not valid.") from None
    message = EmailMessage()
    message["Subject"] = TEST_EMAIL_SUBJECT
    message["From"] = sender
    message["To"] = to
    message["Date"] = format_datetime(now)
    message["Message-ID"] = make_msgid(domain=sender.domain or None)
    local = f"{display_datetime(now)} PKT"
    message.set_content(
        "This is a test email from Cheena FBR POS Software.\n\n"
        "If you received it, the email settings are working. No action is needed.\n\n"
        f"Sent from Super Admin > Email Settings on {local}.\n"
    )
    return message


def send_test_email(
    db: Session,
    *,
    actor: User,
    transport: SmtpTransport,
    redis: Redis,
    recipient: str,
    idempotency_key: uuid.UUID,
) -> CheckOutcome:
    recipient = normalize_email(recipient)
    if not is_valid_email(recipient) or _has_control_chars(recipient):
        raise AppError(422, "invalid_recipient", "Enter a valid recipient email address.")

    replay_key = _idempotency_key(actor, idempotency_key)
    replay = _load_replay(redis, replay_key)
    if replay is not None:
        return replay

    row = get_email_settings(db)
    if row is None:
        raise _not_configured()
    if not row.is_enabled:
        raise AppError(
            409,
            "email_sending_disabled",
            "Email sending is disabled. Enable email sending to send a test email.",
        )
    config = _smtp_config(row)
    tested_version = row.version
    now = clock.utcnow()
    message = build_test_message(row, recipient, now)
    db.rollback()

    guard = _TestGuard(redis, actor, KIND_EMAIL)
    guard.acquire()
    try:
        # Re-check under the lock: a concurrent duplicate may have just finished.
        replay = _load_replay(redis, replay_key)
        if replay is not None:
            return replay
        guard.count()
        ok, code = _run(lambda: transport.send(config, message))
        outcome = CheckOutcome(
            KIND_EMAIL,
            ok,
            code,
            EMAIL_OK_MESSAGE if ok else (failure_message(code) or ""),
            clock.utcnow(),
        )
        # Store the replay first: once SMTP accepted the message, a retry must
        # never send it again, even if recording the audit row fails.
        _store_replay(redis, replay_key, outcome)
        _record_result(
            db,
            actor=actor,
            tested_version=tested_version,
            outcome=outcome,
            extra={"recipient": mask_email(recipient)},
        )
    finally:
        guard.release()
    logger.info("smtp test email by %s: %s", actor.id, code or "accepted")
    return outcome
