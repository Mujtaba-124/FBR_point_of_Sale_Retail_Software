"""Controlled creation of the first Super Admin and Company Admin.

There is no public registration endpoint; these accounts are created only via
the CLI (``python -m app.cli``). Re-running is safe: an existing account is
never modified and a second initial account of the same category is refused.
"""

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.security import (
    hash_password,
    is_valid_email,
    normalize_email,
    validate_password_policy,
)
from app.models import AccessCategory, User

# Serializes concurrent bootstrap runs (arbitrary constant, unique to this app).
_BOOTSTRAP_LOCK_ID = 7_310_001

BOOTSTRAP_CATEGORIES = (AccessCategory.SUPER_ADMIN, AccessCategory.COMPANY_ADMIN)


class BootstrapOutcome(StrEnum):
    CREATED = "created"
    ALREADY_EXISTS = "already_exists"


class BootstrapError(Exception):
    """The request was refused; nothing was changed."""


@dataclass(frozen=True)
class BootstrapResult:
    outcome: BootstrapOutcome
    email: str


def validate_inputs(email: str, full_name: str, password: str) -> list[str]:
    problems: list[str] = []
    if not is_valid_email(email):
        problems.append("Email address is not valid.")
    if not full_name.strip() or len(full_name.strip()) > 200:
        problems.append("Full name is required (max 200 characters).")
    problems.extend(validate_password_policy(password))
    return problems


def create_initial_account(
    db: Session,
    category: AccessCategory,
    email: str,
    full_name: str,
    password: str,
) -> BootstrapResult:
    if category not in BOOTSTRAP_CATEGORIES:
        raise BootstrapError("Only the initial Super Admin and Company Admin can be bootstrapped.")
    problems = validate_inputs(email, full_name, password)
    if problems:
        raise BootstrapError(" ".join(problems))

    email = normalize_email(email)
    # Transaction-scoped advisory lock: concurrent runs wait instead of racing.
    db.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": _BOOTSTRAP_LOCK_ID})

    existing_initial = db.scalar(
        select(User).where(User.access_category == category).order_by(User.created_at).limit(1)
    )
    if existing_initial is not None:
        existing_email = existing_initial.email
        db.rollback()
        if existing_email == email:
            return BootstrapResult(BootstrapOutcome.ALREADY_EXISTS, existing_email)
        raise BootstrapError(
            "An initial account of this type already exists. No new account was created."
        )

    if db.scalar(select(User.id).where(func.lower(User.email) == email)) is not None:
        db.rollback()
        raise BootstrapError("An account with this email already exists. It was not changed.")

    user = User(
        email=email,
        full_name=full_name.strip(),
        password_hash=hash_password(password),
        access_category=category,
        is_active=True,
    )
    db.add(user)
    db.commit()
    return BootstrapResult(BootstrapOutcome.CREATED, email)
