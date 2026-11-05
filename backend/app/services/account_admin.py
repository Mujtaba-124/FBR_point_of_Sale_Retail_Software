"""Operator-level account maintenance (used by the CLI, never exposed over HTTP)."""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import is_valid_email, mask_email, normalize_email, verify_password
from app.models import AccessCategory, AuditEvent, AuthenticationSession, User

logger = logging.getLogger(__name__)

EMAIL_CHANGED = "user.email_changed"
EMAIL_CHANGE_REFUSED = "user.email_change_refused"


class AccountChangeError(Exception):
    """The change was refused; nothing was modified."""


@dataclass(frozen=True)
class EmailChangeResult:
    user_id: uuid.UUID
    access_category: AccessCategory
    old_email: str
    new_email: str
    sessions_revoked: int


def _audit_refusal(db: Session, actor: str, user: User | None, reason: str) -> None:
    db.add(
        AuditEvent(
            action=EMAIL_CHANGE_REFUSED,
            actor=actor,
            target_user_id=user.id if user else None,
            details={"reason": reason, "method": "cli"},
        )
    )
    db.commit()


def change_user_email(
    db: Session,
    current_email: str,
    new_email: str,
    account_password: str,
    actor: str,
) -> EmailChangeResult:
    """Change one account's sign-in email, keeping everything else intact.

    The account's own password must be supplied, so a mistyped or
    unauthorized target account cannot be changed. All of the account's active
    sessions are revoked, and an audit event is written in the same
    transaction. The new address is NOT verified by this operation.
    """
    current = normalize_email(current_email)
    new = normalize_email(new_email)
    if not is_valid_email(new):
        raise AccountChangeError("The new email address is not valid.")

    user = db.scalar(
        select(User).where(func.lower(User.email) == current).with_for_update()
    )
    # One message for "no such account" and "wrong password".
    if user is None or not verify_password(user.password_hash, account_password):
        db.rollback()
        _audit_refusal(db, actor, user, "bad_credentials")
        logger.warning("email change refused: bad credentials for %s", mask_email(current))
        raise AccountChangeError(
            "The current email or the account password is incorrect. Nothing was changed."
        )

    if new == user.email:
        db.rollback()
        raise AccountChangeError(
            "The new email is the same as the current one. Nothing was changed."
        )

    taken = db.scalar(select(User.id).where(func.lower(User.email) == new, User.id != user.id))
    if taken is not None:
        db.rollback()
        _audit_refusal(db, actor, user, "email_in_use")
        raise AccountChangeError(
            "That email address is already used by another account. Nothing was changed."
        )

    old = user.email
    user_id, category = user.id, user.access_category
    user.email = new
    revoked = cast(
        CursorResult[tuple[()]],
        db.execute(
            update(AuthenticationSession)
            .where(
                AuthenticationSession.user_id == user_id,
                AuthenticationSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        ),
    ).rowcount
    db.add(
        AuditEvent(
            action=EMAIL_CHANGED,
            actor=actor,
            target_user_id=user_id,
            details={
                "old_email": old,
                "new_email": new,
                "sessions_revoked": revoked,
                "email_verified": False,
                "method": "cli",
            },
        )
    )
    try:
        db.commit()
    except IntegrityError:  # lost a race with another change to the same address
        db.rollback()
        raise AccountChangeError(
            "That email address is already used by another account. Nothing was changed."
        ) from None

    logger.info(
        "user email changed for %s: %s -> %s (%d sessions revoked)",
        user_id,
        mask_email(old),
        mask_email(new),
        revoked,
    )
    return EmailChangeResult(user_id, category, old, new, revoked)
