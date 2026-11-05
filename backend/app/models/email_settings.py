import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SINGLETON_ID = 1


class EmailSettings(Base):
    """The application's single SMTP configuration (Super Admin managed).

    ``encrypted_smtp_password`` holds an AES-256-GCM token (see
    ``app.core.secret_box``); the key is never stored in the database.
    ``version`` increments on every change (optimistic concurrency).
    """

    __tablename__ = "email_settings"
    __table_args__ = (
        CheckConstraint(f"id = {SINGLETON_ID}", name="ck_email_settings_singleton"),
        CheckConstraint(
            "encryption_mode IN ('starttls', 'ssl')", name="ck_email_settings_encryption_mode"
        ),
        CheckConstraint("smtp_port BETWEEN 1 AND 65535", name="ck_email_settings_port"),
        CheckConstraint(
            "last_test_status IS NULL OR last_test_status IN ('success', 'failure')",
            name="ck_email_settings_last_test_status",
        ),
        CheckConstraint(
            "last_test_kind IS NULL OR last_test_kind IN ('connection', 'email')",
            name="ck_email_settings_last_test_kind",
        ),
    )

    id: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, default=SINGLETON_ID, server_default=text(str(SINGLETON_ID))
    )
    smtp_host: Mapped[str] = mapped_column(String(253), nullable=False)
    smtp_port: Mapped[int] = mapped_column(Integer, nullable=False)
    encryption_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    smtp_username: Mapped[str | None] = mapped_column(String(320))
    encrypted_smtp_password: Mapped[str | None] = mapped_column(Text)
    sender_email: Mapped[str] = mapped_column(String(320), nullable=False)
    sender_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Latest test of any kind, plus the most recent success and failure.
    last_test_status: Mapped[str | None] = mapped_column(String(16))
    last_test_kind: Mapped[str | None] = mapped_column(String(16))
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_code: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
