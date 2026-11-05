"""One-time initial subscription setup (operator CLI only).

This only creates the first record when none exists. Changing an existing
subscription is renewal, which is a separate, later feature.
"""

from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AppSubscription, AuditEvent
from app.models.app_subscription import SINGLETON_ID


class SubscriptionSetupError(Exception):
    """Refused; nothing was changed."""


def configure_initial_subscription(
    db: Session, company_name: str, start: date, expiry: date, actor: str
) -> AppSubscription:
    name = company_name.strip()
    if not name or len(name) > 200:
        raise SubscriptionSetupError("Company name is required (max 200 characters).")
    if expiry < start:
        raise SubscriptionSetupError("The expiry date must be on or after the start date.")
    if db.get(AppSubscription, SINGLETON_ID) is not None:
        raise SubscriptionSetupError(
            "A subscription is already configured. Changing it is a renewal, which is not "
            "available yet. Nothing was changed."
        )

    record = AppSubscription(
        id=SINGLETON_ID, company_name=name, start_date=start, expiry_date=expiry
    )
    db.add(record)
    db.add(
        AuditEvent(
            action="subscription.configured",
            actor=actor,
            details={
                "company_name": name,
                "start_date": start.isoformat(),
                "expiry_date": expiry.isoformat(),
                "method": "cli",
            },
        )
    )
    try:
        db.commit()
    except IntegrityError:  # another run created it first
        db.rollback()
        raise SubscriptionSetupError(
            "A subscription is already configured. Nothing was changed."
        ) from None
    return record
