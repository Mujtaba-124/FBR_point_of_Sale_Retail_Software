"""Super Admin email (SMTP) settings. Every route requires a Super Admin.

State-changing routes are CSRF-protected by ``current_session`` (session
cookie + X-CSRF-Token + Origin check). Company accounts get 403.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from redis import Redis

from app.api.deps import DbSession, SuperAdmin
from app.core.redis import get_redis
from app.schemas.email_settings import (
    CheckResultOut,
    EmailSettingsOut,
    SaveSettingsRequest,
    SendingRequest,
    TestEmailRequest,
)
from app.services import email_settings as svc
from app.services.smtp_transport import SmtpTransport, get_smtp_transport

router = APIRouter(prefix="/super-admin/email-settings", tags=["super-admin"])

Transport = Annotated[SmtpTransport, Depends(get_smtp_transport)]
RedisClient = Annotated[Redis, Depends(get_redis)]


@router.get("", response_model=EmailSettingsOut)
def read_settings(_: SuperAdmin, db: DbSession) -> EmailSettingsOut:
    return EmailSettingsOut.build(svc.get_email_settings(db))


@router.put("", response_model=EmailSettingsOut)
def save_settings(
    payload: SaveSettingsRequest, user: SuperAdmin, db: DbSession
) -> EmailSettingsOut:
    row = svc.save_settings(db, actor=user, data=payload.to_input())
    return EmailSettingsOut.build(row)


@router.put("/sending", response_model=EmailSettingsOut)
def set_sending(payload: SendingRequest, user: SuperAdmin, db: DbSession) -> EmailSettingsOut:
    row = svc.set_sending_enabled(
        db, actor=user, enabled=payload.enabled, expected_version=payload.expected_version
    )
    return EmailSettingsOut.build(row)


@router.post("/test-connection", response_model=CheckResultOut)
def test_connection(
    user: SuperAdmin, db: DbSession, transport: Transport, redis: RedisClient
) -> CheckResultOut:
    """Connect, secure and sign in with the saved settings. Never sends an email."""
    outcome = svc.run_connection_test(db, actor=user, transport=transport, redis=redis)
    return CheckResultOut.build(outcome, svc.get_email_settings(db))


@router.post("/test-email", response_model=CheckResultOut)
def send_test_email(
    payload: TestEmailRequest,
    user: SuperAdmin,
    db: DbSession,
    transport: Transport,
    redis: RedisClient,
) -> CheckResultOut:
    """Send one fixed test message. Requires email sending to be enabled."""
    outcome = svc.send_test_email(
        db,
        actor=user,
        transport=transport,
        redis=redis,
        recipient=payload.recipient_email,
        idempotency_key=payload.idempotency_key,
    )
    return CheckResultOut.build(outcome, svc.get_email_settings(db))
