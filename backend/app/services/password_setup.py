"""One-time password setup links for new Company accounts.

Provisioning flow (no plaintext or temporary password ever exists):
1. The Company Admin creates the account; it gets an unusable random password
   hash and ``must_set_password=True``.
2. A 256-bit random token is generated; only its SHA-256 hash is stored, with
   a 72-hour expiry. The raw token is returned once, to the Company Admin, who
   hands the link to the user. Issuing a new link revokes older ones.
3. The user opens ``/set-password#token=...`` (the token is in the URL
   fragment, so it never reaches server logs or Referer headers), chooses a
   password that passes the policy, and the token is consumed (single use).

Completion is rate limited per client IP and fails closed if Redis is down.
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import AppError
from app.core.security import (
    hash_password,
    hash_token,
    mask_email,
    new_token,
    validate_password_policy,
)
from app.models import AccessCategory, AuditEvent, PasswordSetupToken, User

logger = logging.getLogger(__name__)

SETUP_TTL = timedelta(hours=72)
RATE_WINDOW_SECONDS = 15 * 60
RATE_MAX_ATTEMPTS = 20


def _invalid() -> AppError:
    return AppError(
        400,
        "invalid_setup_link",
        "This setup link is invalid, expired or already used. "
        "Ask your Company Admin for a new link.",
    )


def unusable_password_hash() -> str:
    """A hash of a random secret nobody knows: the account cannot sign in."""
    return hash_password(new_token() + new_token())


def issue_setup_token(db: Session, user: User, actor: User) -> tuple[str, datetime]:
    """Revoke previous links and create a new one. Caller commits."""
    now = clock.utcnow()
    db.execute(
        update(PasswordSetupToken)
        .where(
            PasswordSetupToken.user_id == user.id,
            PasswordSetupToken.used_at.is_(None),
            PasswordSetupToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    token = new_token()
    expires = now + SETUP_TTL
    db.add(
        PasswordSetupToken(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=expires,
            created_by_user_id=actor.id,
        )
    )
    return token, expires


def has_open_link(db: Session, user_id: object) -> datetime | None:
    """Expiry of the user's current unused link, or None if there is none."""
    now = clock.utcnow()
    return db.scalar(
        select(PasswordSetupToken.expires_at)
        .where(
            PasswordSetupToken.user_id == user_id,
            PasswordSetupToken.used_at.is_(None),
            PasswordSetupToken.revoked_at.is_(None),
            PasswordSetupToken.expires_at > now,
        )
        .order_by(PasswordSetupToken.expires_at.desc())
        .limit(1)
    )


@dataclass(frozen=True)
class SetupLinkInfo:
    full_name: str
    masked_email: str
    expires_at: datetime


def _find(db: Session, token: str, *, lock: bool) -> tuple[PasswordSetupToken, User]:
    if not token or len(token) > 200:
        raise _invalid()
    stmt = select(PasswordSetupToken).where(PasswordSetupToken.token_hash == hash_token(token))
    if lock:
        stmt = stmt.with_for_update()
    record = db.scalar(stmt)
    now = clock.utcnow()
    if (
        record is None
        or record.used_at is not None
        or record.revoked_at is not None
        or record.expires_at <= now
    ):
        raise _invalid()
    user = db.get(User, record.user_id)
    if (
        user is None
        or not user.is_active
        or not user.must_set_password
        or user.access_category == AccessCategory.SUPER_ADMIN
    ):
        raise _invalid()
    return record, user


def check_link(db: Session, token: str) -> SetupLinkInfo:
    record, user = _find(db, token, lock=False)
    return SetupLinkInfo(user.full_name, mask_email(user.email), record.expires_at)


def _rate_limit(redis: Redis, ip: str) -> None:
    key = "rl:password_setup:ip:" + hashlib.sha256(ip.encode()).hexdigest()
    try:
        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, RATE_WINDOW_SECONDS, nx=True)
        pipe.ttl(key)
        count, _, ttl = pipe.execute()
    except RedisError:
        logger.exception("password setup rate limiter unavailable")
        raise AppError(
            503, "service_unavailable", "Password setup is temporarily unavailable."
        ) from None
    if int(count) > RATE_MAX_ATTEMPTS:
        raise AppError(
            429,
            "rate_limited",
            "Too many attempts. Please wait and try again.",
            headers={"Retry-After": str(max(int(ttl), 1))},
        )


def complete_setup(db: Session, redis: Redis, *, token: str, password: str, ip: str) -> User:
    _rate_limit(redis, ip)
    problems = validate_password_policy(password)
    try:
        record, user = _find(db, token, lock=True)
        if problems:
            db.rollback()
            raise AppError(422, "weak_password", " ".join(problems))
        now = clock.utcnow()
        user.password_hash = hash_password(password)
        user.must_set_password = False
        record.used_at = now
        db.execute(
            update(PasswordSetupToken)
            .where(
                PasswordSetupToken.user_id == user.id,
                PasswordSetupToken.id != record.id,
                PasswordSetupToken.used_at.is_(None),
                PasswordSetupToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        db.add(
            AuditEvent(
                action="company_user.password_set",
                actor=f"user:{user.id}",
                target_user_id=user.id,
                details={"via": "setup_link"},
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    logger.info("password set via setup link", extra={"user_id": str(user.id)})
    return user
