"""Login and logout business logic."""

import logging
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import (
    burn_password_check,
    hash_password,
    normalize_email,
    password_needs_rehash,
    verify_password,
)
from app.models import AccessCategory, User
from app.services.rate_limit import LoginRateLimiter
from app.services.sessions import IssuedSession, create_session, revoke_token_if_present
from app.services.subscription_access import company_access, subscription_denial

logger = logging.getLogger(__name__)

def _invalid_credentials() -> AppError:
    return AppError(401, "invalid_credentials", "Invalid email or password.")


def _account_inactive() -> AppError:
    return AppError(
        403, "account_inactive", "This account is disabled. Contact your administrator."
    )


def find_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == normalize_email(email)))


def login(
    db: Session,
    request: Request,
    limiter: LoginRateLimiter,
    email: str,
    password: str,
    ip: str,
) -> tuple[User, IssuedSession]:
    email = normalize_email(email)
    limiter.check_and_count_attempt(email, ip)

    user = find_user_by_email(db, email)
    if user is None:
        burn_password_check(password)
        limiter.record_failure(email)
        logger.info("login failed: unknown account")
        raise _invalid_credentials()

    if not verify_password(user.password_hash, password):
        limiter.record_failure(email)
        logger.info("login failed: wrong password", extra={"user_id": str(user.id)})
        raise _invalid_credentials()

    # The password is correct, so revealing the account state leaks nothing new.
    if not user.is_active:
        logger.info("login refused: inactive account", extra={"user_id": str(user.id)})
        raise _account_inactive()

    # Company accounts need a valid subscription; the Super Admin never does,
    # so renewal stays possible after expiry. Refused before any session is
    # created, so no usable session cookie is issued.
    if user.access_category != AccessCategory.SUPER_ADMIN:
        access = company_access(db)
        if not access.allowed:
            limiter.record_success(email)  # correct credentials: not a guessing attempt
            logger.info(
                "login refused: company subscription %s",
                access.status,
                extra={"user_id": str(user.id)},
            )
            raise subscription_denial(access)

    limiter.record_success(email)
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = datetime.now(UTC)

    revoke_token_if_present(db, request)
    issued = create_session(db, user, request)
    db.commit()
    logger.info("login succeeded", extra={"user_id": str(user.id)})
    return user, issued
