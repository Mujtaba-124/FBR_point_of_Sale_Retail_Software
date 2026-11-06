"""Company roles, their permissions, and one-time password setup links."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

SYSTEM_COMPANY_ADMIN = "company_admin"
SYSTEM_COMPANY_USER = "company_user"


class CompanyRole(Base):
    """A Company Workspace role. ``system_key`` marks the two protected roles."""

    __tablename__ = "company_roles"
    __table_args__ = (
        Index("uq_company_roles_name_lower", func.lower(text("name")), unique=True),
        CheckConstraint("length(trim(name)) >= 2", name="ck_company_roles_name"),
        CheckConstraint(
            "system_key IS NULL OR system_key IN ('company_admin', 'company_user')",
            name="ck_company_roles_system_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))
    system_key: Mapped[str | None] = mapped_column(String(32), unique=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
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

    permissions: Mapped[list["CompanyRolePermission"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def is_system(self) -> bool:
        return self.system_key is not None

    @property
    def permission_keys(self) -> set[str]:
        return {p.permission for p in self.permissions}


class CompanyRolePermission(Base):
    __tablename__ = "company_role_permissions"
    __table_args__ = (
        CheckConstraint(
            r"permission ~ '^[a-z_]+\.[a-z_]+$'", name="ck_company_role_permissions_key"
        ),
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("company_roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission: Mapped[str] = mapped_column(String(64), primary_key=True)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PasswordSetupToken(Base):
    """Single-use password setup link. Only the SHA-256 hash of the token is stored."""

    __tablename__ = "password_setup_tokens"
    __table_args__ = (Index("ix_password_setup_tokens_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
