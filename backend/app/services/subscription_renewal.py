"""Subscription renewal (Super Admin only).

Rules (calendar days in Asia/Karachi, see ``app.services.subscription``):

- A subscription must be configured; renewal never creates one.
- The new expiry date must be strictly later than the current expiry date AND
  strictly later than today, so a renewal after expiry makes the account active.
- The start date never changes. Shortening or arbitrary edits are not offered.
- At most ``MAX_EXTENSION_DAYS`` beyond max(current expiry, today), to catch typos.

Concurrency and duplicates:

- The single subscription row is locked with ``SELECT ... FOR UPDATE`` for the
  whole transaction, so concurrent renewals are serialized.
- The caller sends the expiry date it saw (``expected_expiry_date``). If the row
  changed since, the request is rejected with 409 instead of overwriting.
- Each request carries a client-generated ``idempotency_key`` (unique in the
  history table). Replaying the same key returns the original renewal; reusing
  it for different input is a 409.
- The renewal row, the subscription update and the audit event are written in
  one transaction: either all of them persist or none do.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import AppSubscription, AuditEvent, SubscriptionRenewal, User
from app.models.app_subscription import SINGLETON_ID
from app.services.reminder_outbox import cancel_obsolete
from app.services.subscription import business_today

logger = logging.getLogger(__name__)

MAX_EXTENSION_DAYS = 3650
NOTE_MAX_LENGTH = 500


@dataclass(frozen=True)
class RenewalWindow:
    can_renew: bool
    min_new_expiry_date: date | None
    max_new_expiry_date: date | None


@dataclass(frozen=True)
class RenewalOutcome:
    renewal: SubscriptionRenewal
    created: bool


def renewal_window(record: AppSubscription | None, today: date) -> RenewalWindow:
    if record is None or record.expiry_date < record.start_date:
        return RenewalWindow(False, None, None)
    baseline = max(record.expiry_date, today)
    return RenewalWindow(
        True, baseline + timedelta(days=1), baseline + timedelta(days=MAX_EXTENSION_DAYS)
    )


def _invalid(message: str) -> AppError:
    return AppError(422, "invalid_renewal", message)


def _conflict(code: str, message: str) -> AppError:
    return AppError(409, code, message)


def _clean_note(note: str | None) -> str | None:
    if note is None:
        return None
    note = note.strip()
    if len(note) > NOTE_MAX_LENGTH:
        raise _invalid(f"The renewal note must be at most {NOTE_MAX_LENGTH} characters.")
    return note or None


def _record_audit(db: Session, actor: User, renewal: SubscriptionRenewal) -> None:
    db.add(
        AuditEvent(
            action="subscription.renewed",
            actor=f"user:{actor.id}",
            details={
                "subscription_id": renewal.subscription_id,
                "renewal_id": str(renewal.id),
                "previous_expiry_date": renewal.previous_expiry_date.isoformat(),
                "new_expiry_date": renewal.new_expiry_date.isoformat(),
                "renewed_by_user_id": str(actor.id),
            },
        )
    )


def renew_subscription(
    db: Session,
    *,
    actor: User,
    new_expiry_date: date,
    expected_expiry_date: date,
    idempotency_key: uuid.UUID,
    note: str | None = None,
    today: date | None = None,
) -> RenewalOutcome:
    today = today or business_today()
    note = _clean_note(note)

    # Lock the single subscription row until commit/rollback.
    record = db.scalar(
        select(AppSubscription).where(AppSubscription.id == SINGLETON_ID).with_for_update()
    )
    if record is None:
        db.rollback()
        raise AppError(
            404, "subscription_not_configured", "No subscription has been configured to renew."
        )

    previous = db.scalar(
        select(SubscriptionRenewal).where(SubscriptionRenewal.idempotency_key == idempotency_key)
    )
    if previous is not None:
        same = (
            previous.new_expiry_date == new_expiry_date
            and previous.previous_expiry_date == expected_expiry_date
            and previous.renewed_by_user_id == actor.id
        )
        db.rollback()
        if same:
            return RenewalOutcome(previous, created=False)
        raise _conflict(
            "idempotency_conflict",
            "This renewal request was already used with different details. Start a new renewal.",
        )

    if record.expiry_date != expected_expiry_date:
        db.rollback()
        raise _conflict(
            "stale_subscription",
            "The subscription was changed after this form was opened. Reload and try again.",
        )

    window = renewal_window(record, today)
    if not window.can_renew:
        db.rollback()
        raise _conflict("subscription_invalid", "The stored subscription dates are invalid.")
    if new_expiry_date <= record.expiry_date:
        db.rollback()
        raise _invalid("The new expiry date must be later than the current expiry date.")
    if new_expiry_date <= today:
        db.rollback()
        raise _invalid(
            "The new expiry date must be later than today so the subscription is active."
        )
    assert window.max_new_expiry_date is not None
    if new_expiry_date > window.max_new_expiry_date:
        db.rollback()
        raise _invalid(
            f"A renewal can extend the subscription by at most {MAX_EXTENSION_DAYS} days."
        )

    renewal = SubscriptionRenewal(
        id=uuid.uuid4(),
        subscription_id=record.id,
        previous_expiry_date=record.expiry_date,
        new_expiry_date=new_expiry_date,
        renewed_by_user_id=actor.id,
        renewal_note=note,
        idempotency_key=idempotency_key,
    )
    record.expiry_date = new_expiry_date
    record.last_renewed_on = today
    db.add(renewal)
    try:
        db.flush()
        _record_audit(db, actor, renewal)
        # Same transaction: queued reminders for the old expiry date can never be
        # sent once the renewal is committed (workers also re-check before sending).
        cancel_obsolete(db, current_expiry=new_expiry_date, actor=f"user:{actor.id}")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _conflict(
            "renewal_conflict", "The renewal could not be saved because of a conflicting change."
        ) from None
    except Exception:
        db.rollback()
        raise

    logger.info(
        "subscription renewed: %s -> %s by %s",
        renewal.previous_expiry_date,
        renewal.new_expiry_date,
        actor.id,
    )
    return RenewalOutcome(renewal, created=True)


def list_renewals(db: Session, limit: int, offset: int) -> tuple[list[SubscriptionRenewal], int]:
    total = db.scalar(select(func.count()).select_from(SubscriptionRenewal)) or 0
    rows = db.scalars(
        select(SubscriptionRenewal)
        .order_by(SubscriptionRenewal.renewed_at.desc(), SubscriptionRenewal.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return list(rows), int(total)
