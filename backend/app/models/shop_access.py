"""Which shops a Company User may work with (operational record scope).

``user_shop_access`` holds one row per Company User:
- ``none``      no shop data at all (the default for new and pre-existing users)
- ``selected``  only the shops listed in ``user_shop_assignments``
- ``all``       every registered shop, including shops created later
The protected Company Admin never has a row: it always has company-wide scope.

``user_shop_assignments`` rows can exist only while the user's mode is
``selected``: the composite foreign key (user_id, access_mode) points at the
access row, whose access_mode must then also be 'selected'. Deferred
constraint triggers (migration 0010) also require at least one shop in
``selected`` mode and allow access rows for Company Users only.

Shops are referenced by their immutable ID (never name or code). Assignments
are kept when a shop is deactivated, so historical reads keep working.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

MODE_NONE = "none"
MODE_SELECTED = "selected"
MODE_ALL = "all"
ACCESS_MODES = (MODE_NONE, MODE_SELECTED, MODE_ALL)


class UserShopAccess(Base):
    __tablename__ = "user_shop_access"
    __table_args__ = (
        CheckConstraint(
            "access_mode IN ('none', 'selected', 'all')", name="ck_user_shop_access_mode"
        ),
        CheckConstraint("version >= 1", name="ck_user_shop_access_version"),
        # Target of the assignments' composite foreign key.
        UniqueConstraint("user_id", "access_mode", name="uq_user_shop_access_user_mode"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    access_mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default="none")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class UserShopAssignment(Base):
    __tablename__ = "user_shop_assignments"
    __table_args__ = (
        CheckConstraint("access_mode = 'selected'", name="ck_user_shop_assignments_mode"),
        ForeignKeyConstraint(
            ["user_id", "access_mode"],
            ["user_shop_access.user_id", "user_shop_access.access_mode"],
            name="fk_user_shop_assignments_access",
            ondelete="CASCADE",
        ),
        Index("ix_user_shop_assignments_shop_id", "shop_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="RESTRICT"), primary_key=True
    )
    access_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default=MODE_SELECTED, server_default=text("'selected'")
    )
    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
