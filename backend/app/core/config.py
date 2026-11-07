from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment variables.

    Security-relevant defaults are the *production* values. Local development
    opts out explicitly (for example ``COOKIE_SECURE=false`` over plain HTTP).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Cheena FBR POS Software"
    environment: str = "development"

    database_url: str
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None

    # Browser origins allowed to make state-changing requests (and CORS).
    cors_origins: str = "http://localhost:3000"

    # --- Sessions -----------------------------------------------------------
    # Secure cookies use the "__Host-" prefix (Secure, Path=/, no Domain).
    cookie_secure: bool = True
    session_absolute_ttl_minutes: int = 12 * 60
    session_idle_ttl_minutes: int = 60

    # --- Login rate limiting (fixed window, stored in Redis) ----------------
    login_rate_window_seconds: int = 15 * 60
    login_max_failures_per_email: int = 5
    login_max_attempts_per_ip: int = 20

    # Use the first X-Forwarded-For hop as the client IP. Enable only when the
    # backend is reachable exclusively through a trusted proxy.
    trust_proxy_headers: bool = False

    # --- Email settings -------------------------------------------------------
    # Base64url-encoded 32-byte key for AES-256-GCM. Must be set through the
    # environment/secret store, never the database. Keep it backed up
    # separately from database backups: without it, a stored SMTP password
    # cannot be decrypted.
    email_settings_encryption_key: str | None = None
    # Comma-separated old keys, accepted for decryption only (key rotation).
    email_settings_previous_keys: str = ""
    # Allow SMTP hosts on private/loopback networks. Development/testing only;
    # rejected in production.
    smtp_allow_private_hosts: bool = False
    # Separate AES-256-GCM key for shop FBR tokens (key separation from SMTP).
    # Back it up separately from database backups; rotate via the previous list.
    fbr_token_encryption_key: str | None = None
    fbr_token_previous_keys: str = ""
    smtp_timeout_seconds: float = 15.0
    test_email_rate_window_seconds: int = 15 * 60
    test_email_max_per_window: int = 5
    # "smtp" (real delivery) or "sink" (development/QA: write .eml files to
    # EMAIL_SINK_DIR instead of sending). "sink" is refused in production.
    email_transport: Literal["smtp", "sink"] = "smtp"
    email_sink_dir: str = "/tmp/cheena_email_sink"

    # --- Background schedule (Celery Beat) ---------------------------------
    # Unset: reminders are evaluated at minutes :05 and :35. The end-to-end
    # verification sets short intervals so simulated days pass quickly.
    reminder_evaluate_interval_seconds: float | None = None
    outbox_dispatch_interval_seconds: float = 60.0

    # --- End-to-end verification mode (disposable QA stack only) -----------
    # Enables the simulated clock (app.core.clock) and SMTP fault injection in
    # the file sink. Refused in production, without the sink transport, and for
    # any database whose name does not end in "_e2e".
    e2e_test_mode: bool = False

    # --- Excel sales uploads ---------------------------------------------------
    # Private directory for original files (a Docker volume; back it up with the
    # database). Never served directly: downloads go through an authorized API.
    upload_storage_dir: str = "/var/lib/cheena/uploads"
    upload_max_bytes: int = 5 * 1024 * 1024
    upload_max_rows: int = 5_000
    # Decompression guard for the .xlsx ZIP container.
    upload_max_uncompressed_bytes: int = 60 * 1024 * 1024
    upload_max_zip_entries: int = 200

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def session_cookie_name(self) -> str:
        return "__Host-cheena_session" if self.cookie_secure else "cheena_session"

    @property
    def csrf_cookie_name(self) -> str:
        return "__Host-cheena_csrf" if self.cookie_secure else "cheena_csrf"

    @property
    def inactive_cookie_names(self) -> tuple[str, str]:
        """Session and CSRF cookie names of the *other* COOKIE_SECURE mode.

        A browser can still hold them from a time the setting was different. A
        leftover CSRF cookie is harmful: the browser lists both, the client may
        send the stale token, and every state-changing request then fails CSRF.
        """
        if self.cookie_secure:
            return ("cheena_session", "cheena_csrf")
        return ("__Host-cheena_session", "__Host-cheena_csrf")

    @model_validator(mode="after")
    def _forbid_insecure_production(self) -> "Settings":
        if self.environment == "production" and not self.cookie_secure:
            raise ValueError("COOKIE_SECURE must be true in production")
        if self.environment == "production" and self.smtp_allow_private_hosts:
            raise ValueError("SMTP_ALLOW_PRIVATE_HOSTS must be false in production")
        if self.environment == "production" and self.email_transport != "smtp":
            raise ValueError("EMAIL_TRANSPORT must be smtp in production")
        if self.e2e_test_mode:
            if self.environment == "production":
                raise ValueError("E2E_TEST_MODE must be false in production")
            if self.email_transport != "sink":
                raise ValueError("E2E_TEST_MODE requires EMAIL_TRANSPORT=sink")
            database = self.database_url.rsplit("/", 1)[-1].split("?", 1)[0]
            if not database.endswith("_e2e"):
                raise ValueError("E2E_TEST_MODE is only allowed on a database named *_e2e")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
