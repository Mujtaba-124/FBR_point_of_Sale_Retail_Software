"""Fixed subscription expiry reminder schedule and recipient selection.

Schedule (Asia/Karachi calendar days; the expiry date is inclusive, i.e. the
subscription is valid all day on the expiry date):

    offset = today - expiry_date
    -15 .. -1   one reminder per day before expiry ("expires in N days")
     0          expiry day ("expires today", still valid today)
     1 .. 5     one reminder per day after expiry ("expired N days ago")

Nothing is scheduled outside that window, before the subscription start date,
or for an unconfigured/invalid subscription.

Recipients:
- Super Admin: the email of the single active Super Admin account. If there is
  no active Super Admin, or more than one (ambiguous), none is chosen.
- Company Admin: every ACTIVE Company Admin with a structurally valid email.
  Company Users are never recipients.
- Addresses are normalized (trim + lower-case) and de-duplicated; one copy per
  address per reminder, with every category that address belongs to.
"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import is_valid_email, normalize_email
from app.models import AccessCategory, AppSubscription, User
from app.models.reminders import DAYS_AFTER, DAYS_BEFORE

CATEGORY_SUPER_ADMIN = "super_admin"
CATEGORY_COMPANY_ADMIN = "company_admin"


@dataclass(frozen=True)
class ReminderStage:
    days_offset: int

    @property
    def kind(self) -> str:
        if self.days_offset < 0:
            return "before_expiry"
        if self.days_offset == 0:
            return "expiry_day"
        return "after_expiry"

    @property
    def days(self) -> int:
        """Days remaining (before expiry) or days since expiry (after)."""
        return abs(self.days_offset)

    @property
    def label(self) -> str:
        if self.days_offset < 0:
            return f"{self.days} {'day' if self.days == 1 else 'days'} before expiry"
        if self.days_offset == 0:
            return "Expiry day"
        return f"{self.days} {'day' if self.days == 1 else 'days'} after expiry"


def stage_for(expiry_date: date, today: date) -> ReminderStage | None:
    offset = (today - expiry_date).days
    if -DAYS_BEFORE <= offset <= DAYS_AFTER:
        return ReminderStage(offset)
    return None


def due_stage(record: AppSubscription | None, today: date) -> ReminderStage | None:
    """Today's reminder stage, or None when nothing is scheduled for today."""
    if record is None or record.expiry_date < record.start_date:
        return None
    if today < record.start_date:
        return None
    return stage_for(record.expiry_date, today)


def schedule_window(expiry_date: date) -> tuple[date, date]:
    from datetime import timedelta

    return expiry_date - timedelta(days=DAYS_BEFORE), expiry_date + timedelta(days=DAYS_AFTER)


@dataclass
class Recipient:
    email: str
    categories: list[str] = field(default_factory=list)


@dataclass
class RecipientResolution:
    recipients: list[Recipient]
    super_admin_status: str  # "selected" | "disabled" | "none" | "ambiguous" | "invalid"
    company_admin_count: int
    skipped_company_admins: int  # active Company Admins without a valid email


def _usable(email: str) -> str | None:
    normalized = normalize_email(email)
    if not is_valid_email(normalized) or any(ord(c) < 32 or ord(c) == 127 for c in normalized):
        return None
    return normalized


def resolve_recipients(
    db: Session, *, notify_super_admin: bool, notify_company_admin: bool
) -> RecipientResolution:
    by_email: dict[str, Recipient] = {}

    def add(email: str, category: str) -> None:
        entry = by_email.setdefault(email, Recipient(email))
        if category not in entry.categories:
            entry.categories.append(category)

    super_status = "disabled"
    if notify_super_admin:
        supers = db.scalars(
            select(User).where(
                User.access_category == AccessCategory.SUPER_ADMIN, User.is_active.is_(True)
            )
        ).all()
        if not supers:
            super_status = "none"
        elif len(supers) > 1:
            super_status = "ambiguous"
        else:
            email = _usable(supers[0].email)
            super_status = "selected" if email else "invalid"
            if email:
                add(email, CATEGORY_SUPER_ADMIN)

    company_count = skipped = 0
    if notify_company_admin:
        admins = db.scalars(
            select(User)
            .where(User.access_category == AccessCategory.COMPANY_ADMIN, User.is_active.is_(True))
            .order_by(User.created_at)
        ).all()
        for admin in admins:
            email = _usable(admin.email)
            if email is None:
                skipped += 1
                continue
            company_count += 1
            add(email, CATEGORY_COMPANY_ADMIN)

    return RecipientResolution(
        recipients=sorted(by_email.values(), key=lambda r: r.email),
        super_admin_status=super_status,
        company_admin_count=company_count,
        skipped_company_admins=skipped,
    )
