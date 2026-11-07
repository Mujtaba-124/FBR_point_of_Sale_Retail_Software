"""Test configuration.

Tests never touch the development database. They run against a separate,
disposable PostgreSQL database (``cheena_database_test``, created on demand
on the same server) and Redis logical database 15. The environment is
rewritten *before* the application is imported so every engine, settings
object and Redis client points at those isolated resources.
"""

import base64
import os
import secrets
import tempfile
from collections.abc import Iterator
from pathlib import Path

TEST_DB_NAME = "cheena_database_test"
TEST_REDIS_URL = "redis://redis:6379/15"

_server_url = os.environ["DATABASE_URL"].rsplit("/", 1)[0]
os.environ["DATABASE_URL"] = f"{_server_url}/{TEST_DB_NAME}"
os.environ["REDIS_URL"] = TEST_REDIS_URL
os.environ["ENVIRONMENT"] = "test"
os.environ["COOKIE_SECURE"] = "true"
os.environ["TRUST_PROXY_HEADERS"] = "false"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
# A fresh random key per test run; never the development key.
os.environ["EMAIL_SETTINGS_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(
    secrets.token_bytes(32)
).decode()
os.environ["EMAIL_SETTINGS_PREVIOUS_KEYS"] = ""
os.environ["FBR_TOKEN_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
os.environ["FBR_TOKEN_PREVIOUS_KEYS"] = ""
os.environ["SMTP_ALLOW_PRIVATE_HOSTS"] = "false"
# Original Excel uploads go to a throwaway directory, never the real volume.
os.environ["UPLOAD_STORAGE_DIR"] = tempfile.mkdtemp(prefix="cheena_uploads_test_")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.core.redis import get_redis  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.session import get_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AccessCategory, User  # noqa: E402

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_INI.parent / "alembic"))
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    return cfg


def _ensure_test_database() -> None:
    admin = create_engine(f"{_server_url}/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": TEST_DB_NAME}
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def _test_database() -> Iterator[None]:
    _ensure_test_database()
    command.upgrade(alembic_config(), "head")
    yield
    get_engine().dispose()


@pytest.fixture(autouse=True)
def _clean_state() -> Iterator[None]:
    """Empty the disposable test resources before each test (never the dev DB)."""
    engine = get_engine()
    with engine.begin() as conn:
        assert conn.scalar(text("SELECT current_database()")) == TEST_DB_NAME
        # subscription_renewals is append-only via a trigger; only in this
        # disposable test database are triggers bypassed to reset it.
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        conn.execute(text("DELETE FROM subscription_renewals"))
        # Sales uploads are append-only too; uploads reference shops, so first.
        conn.execute(text("DELETE FROM sales_records"))
        conn.execute(text("DELETE FROM upload_revisions"))
        conn.execute(text("DELETE FROM upload_batches"))
        conn.execute(text("SET LOCAL session_replication_role = origin"))
        conn.execute(text("DELETE FROM email_delivery_attempts"))
        conn.execute(text("DELETE FROM email_outbox"))
        # Assignments restrict shop deletion; removing the access rows cascades them.
        conn.execute(text("DELETE FROM user_shop_access"))
        conn.execute(text("DELETE FROM shops"))
        # The allowance row cannot be deleted (trigger); reset it to the migration state.
        conn.execute(
            text(
                "UPDATE shop_allowance SET mode = 'unlimited', max_shops = NULL, "
                "version = 1, updated_by_user_id = NULL"
            )
        )
        conn.execute(text("DELETE FROM app_subscription"))
        conn.execute(text("DELETE FROM email_settings"))
        conn.execute(text("DELETE FROM subscription_reminder_settings"))
        conn.execute(text("INSERT INTO subscription_reminder_settings (id) VALUES (1)"))
        conn.execute(text("DELETE FROM audit_events"))
        conn.execute(text("DELETE FROM authentication_sessions"))
        conn.execute(text("DELETE FROM password_setup_tokens"))
        conn.execute(text("DELETE FROM users"))
        # Custom roles only; the two system roles come from the migration.
        conn.execute(text("DELETE FROM company_roles WHERE system_key IS NULL"))
    redis = get_redis()
    assert redis.connection_pool.connection_kwargs.get("db") == 15
    redis.flushdb()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def db() -> Iterator[Session]:
    session = sessionmaker(bind=get_engine(), autoflush=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> Iterator[TestClient]:
    # HTTPS base URL so the client sends back the Secure (__Host-) cookies.
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def random_password() -> str:
    return secrets.token_urlsafe(18) + "aA1!"


@pytest.fixture
def make_user(db: Session):
    def _make(
        category: AccessCategory,
        email: str | None = None,
        active: bool = True,
    ) -> tuple[str, str]:
        email = email or f"{category.value}-{secrets.token_hex(4)}@example.test"
        password = random_password()
        db.add(
            User(
                email=email,
                full_name=f"Test {category.value}",
                password_hash=hash_password(password),
                access_category=category,
                is_active=active,
            )
        )
        db.commit()
        return email, password

    return _make


@pytest.fixture
def valid_subscription(db: Session) -> None:
    """A currently valid subscription. Company access is fail-closed without one,
    so tests that sign Company accounts in must use this fixture."""
    from datetime import timedelta

    from app.models import AppSubscription
    from app.services.subscription import business_today

    today = business_today()
    db.add(
        AppSubscription(
            company_name="Test Company",
            start_date=today - timedelta(days=30),
            expiry_date=today + timedelta(days=335),
        )
    )
    db.commit()


def login(client: TestClient, email: str, password: str):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def csrf_header(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("__Host-cheena_csrf") or ""}
