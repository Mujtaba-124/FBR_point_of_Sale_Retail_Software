"""Email settings API models. No model ever carries the SMTP password back out."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models import EmailSettings
from app.services import email_settings as svc
from app.services.smtp_transport import ALLOWED_PORTS


class SmtpSettingsOut(BaseModel):
    smtp_host: str
    smtp_port: int
    encryption_mode: Literal["starttls", "ssl"]
    smtp_username: str | None
    # Only whether a password is stored, never the value or its ciphertext.
    password_set: bool
    password_readable: bool
    sender_email: str
    sender_name: str
    is_enabled: bool
    version: int
    updated_at: datetime


class TestHistoryOut(BaseModel):
    last_test_status: Literal["success", "failure"] | None
    last_test_kind: Literal["connection", "email"] | None
    last_test_at: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_failure_code: str | None
    last_failure_message: str | None


class EmailSettingsOut(BaseModel):
    status: Literal["not_configured", "configured", "disabled"]
    encryption_ready: bool
    allowed_ports: list[int]
    settings: SmtpSettingsOut | None
    history: TestHistoryOut | None

    @classmethod
    def build(cls, row: EmailSettings | None) -> "EmailSettingsOut":
        from app.core import secret_box

        settings = history = None
        if row is not None:
            settings = SmtpSettingsOut(
                smtp_host=row.smtp_host,
                smtp_port=row.smtp_port,
                encryption_mode=row.encryption_mode,  # type: ignore[arg-type]
                smtp_username=row.smtp_username,
                password_set=row.encrypted_smtp_password is not None,
                password_readable=svc.password_readable(row),
                sender_email=row.sender_email,
                sender_name=row.sender_name,
                is_enabled=row.is_enabled,
                version=row.version,
                updated_at=row.updated_at,
            )
            history = TestHistoryOut(
                last_test_status=row.last_test_status,  # type: ignore[arg-type]
                last_test_kind=row.last_test_kind,  # type: ignore[arg-type]
                last_test_at=row.last_test_at,
                last_success_at=row.last_success_at,
                last_failure_at=row.last_failure_at,
                last_failure_code=row.last_failure_code,
                last_failure_message=svc.failure_message(row.last_failure_code),
            )
        return cls(
            status=svc.status_of(row),  # type: ignore[arg-type]
            encryption_ready=secret_box.encryption_available(),
            allowed_ports=sorted(ALLOWED_PORTS),
            settings=settings,
            history=history,
        )


class SaveSettingsRequest(BaseModel):
    smtp_host: str = Field(max_length=253)
    smtp_port: int = Field(ge=1, le=65535)
    encryption_mode: Literal["starttls", "ssl"]
    smtp_username: str | None = Field(default=None, max_length=320)
    # Write-only. Blank or omitted keeps the stored password.
    smtp_password: str | None = Field(default=None, max_length=256)
    sender_email: str = Field(max_length=320)
    sender_name: str = Field(max_length=200)
    # None when creating the settings for the first time.
    expected_version: int | None = Field(default=None, ge=1)

    def to_input(self) -> svc.SettingsInput:
        return svc.SettingsInput(
            smtp_host=self.smtp_host,
            smtp_port=self.smtp_port,
            encryption_mode=self.encryption_mode,
            smtp_username=self.smtp_username,
            smtp_password=self.smtp_password,
            sender_email=self.sender_email,
            sender_name=self.sender_name,
            expected_version=self.expected_version,
        )


class SendingRequest(BaseModel):
    enabled: bool
    expected_version: int = Field(ge=1)


class TestEmailRequest(BaseModel):
    recipient_email: str = Field(max_length=320)
    idempotency_key: uuid.UUID


class CheckResultOut(BaseModel):
    kind: Literal["connection", "email"]
    ok: bool
    code: str | None
    message: str
    tested_at: datetime
    replayed: bool
    email_settings: EmailSettingsOut

    @classmethod
    def build(cls, outcome: svc.CheckOutcome, row: EmailSettings | None) -> "CheckResultOut":
        return cls(
            kind=outcome.kind,  # type: ignore[arg-type]
            ok=outcome.ok,
            code=outcome.code,
            message=outcome.message,
            tested_at=outcome.tested_at,
            replayed=outcome.replayed,
            email_settings=EmailSettingsOut.build(row),
        )
