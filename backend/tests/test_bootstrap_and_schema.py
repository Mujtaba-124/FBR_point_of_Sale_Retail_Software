"""Bootstrap safety, database constraints and migration reversibility."""

import io

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.cli import main
from app.core.security import hash_password
from app.models import AccessCategory, User
from app.services.bootstrap import (
    BootstrapError,
    BootstrapOutcome,
    create_initial_account,
)
from tests.conftest import alembic_config, random_password


def _bootstrap(db, category, email, password=None):
    return create_initial_account(
        db, category, email, "Initial Account", password or random_password()
    )


def test_bootstrap_creates_super_admin(db: Session):
    result = _bootstrap(db, AccessCategory.SUPER_ADMIN, "Owner@Example.test")
    assert result.outcome is BootstrapOutcome.CREATED
    user = db.scalar(select(User))
    assert user.email == "owner@example.test"
    assert user.access_category is AccessCategory.SUPER_ADMIN
    assert user.password_hash.startswith("$argon2id$")


def test_rerunning_bootstrap_never_overwrites_credentials(db: Session):
    _bootstrap(db, AccessCategory.SUPER_ADMIN, "owner@example.test")
    original_hash = db.scalar(select(User.password_hash))

    again = _bootstrap(db, AccessCategory.SUPER_ADMIN, "owner@example.test")

    assert again.outcome is BootstrapOutcome.ALREADY_EXISTS
    db.expire_all()
    assert db.scalar(select(User.password_hash)) == original_hash


def test_second_super_admin_is_refused(db: Session):
    _bootstrap(db, AccessCategory.SUPER_ADMIN, "owner@example.test")
    with pytest.raises(BootstrapError):
        _bootstrap(db, AccessCategory.SUPER_ADMIN, "another@example.test")
    assert len(db.scalars(select(User)).all()) == 1


def test_company_admin_cannot_reuse_an_existing_email(db: Session):
    _bootstrap(db, AccessCategory.SUPER_ADMIN, "owner@example.test")
    with pytest.raises(BootstrapError):
        _bootstrap(db, AccessCategory.COMPANY_ADMIN, "OWNER@example.test")


def test_bootstrap_rejects_weak_passwords_and_company_users(db: Session):
    with pytest.raises(BootstrapError):
        _bootstrap(db, AccessCategory.SUPER_ADMIN, "owner@example.test", password="short")
    with pytest.raises(BootstrapError):
        _bootstrap(db, AccessCategory.COMPANY_USER, "user@example.test")
    assert db.scalars(select(User)).all() == []


def test_cli_is_safe_to_rerun_and_never_prints_the_password(db: Session):
    password = random_password()
    args = ["create-company-admin", "--email", "admin@example.test", "--name", "Admin",
            "--password-stdin"]

    out = io.StringIO()
    assert main(args, stdin=io.StringIO(password + "\n"), out=out) == 0
    assert "Created Company Admin admin@example.test" in out.getvalue()

    rerun = io.StringIO()
    assert main(args, stdin=io.StringIO(random_password() + "\n"), out=rerun) == 0
    assert "already exists" in rerun.getvalue()

    other = io.StringIO()
    other_args = ["create-company-admin", "--email", "second@example.test", "--name", "X",
                  "--password-stdin"]
    assert main(other_args, stdin=io.StringIO(password + "\n"), out=other) == 1

    for output in (out, rerun, other):
        assert password not in output.getvalue()
    assert len(db.scalars(select(User)).all()) == 1


def test_email_uniqueness_is_case_insensitive_in_the_database(db: Session):
    for email in ("Same@Example.test", "same@example.test"):
        db.add(User(email=email, full_name="X", password_hash=hash_password("x" * 12),
                    access_category=AccessCategory.COMPANY_USER))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_access_category_is_constrained_by_the_database(db: Session):
    from sqlalchemy import text
    from sqlalchemy.exc import DataError

    with pytest.raises(DataError):
        db.execute(text(
            "INSERT INTO users (email, full_name, password_hash, access_category) "
            "VALUES ('x@example.test', 'X', 'h', 'tenant_admin')"
        ))
    db.rollback()


def test_migration_downgrades_and_upgrades_cleanly() -> None:
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
