import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    FetchedValue,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AccessCategory(enum.StrEnum):
    """Fixed access tiers. Company User rights come from their company role."""

    SUPER_ADMIN = "super_admin"
    COMPANY_ADMIN = "company_admin"
    COMPANY_USER = "company_user"


access_category_enum = Enum(
    AccessCategory,
    name="access_category",
    values_callable=lambda e: [m.value for m in e],
)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # Case-insensitive uniqueness, enforced by the database.
        Index("uq_users_email_lower", func.lower(text("email")), unique=True),
        Index("ix_users_access_category", "access_category"),
        Index("ix_users_company_role_id", "company_role_id"),
        CheckConstraint(
            "(access_category = 'super_admin') = (company_role_id IS NULL)",
            name="ck_users_company_role",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    access_category: Mapped[AccessCategory] = mapped_column(access_category_enum, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Company accounts only (NULL for Super Admin). A database trigger assigns the
    # matching system role when an account is created without one.
    company_role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("company_roles.id", ondelete="RESTRICT"),
        server_default=FetchedValue(),  # set by the trigger; re-read after INSERT
    )
    # True until the user completes their one-time password setup link.
    must_set_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
