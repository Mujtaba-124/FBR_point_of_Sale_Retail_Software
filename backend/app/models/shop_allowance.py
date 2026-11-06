"""Shop Allowance: how many shops the company may register (Super Admin only).

A dedicated singleton row (``id`` fixed to 1), deliberately separate from
``app_subscription`` so allowance changes can never touch the subscription
dates or renewal history. Unlimited is an explicit mode with ``max_shops``
NULL, never a sentinel number; a CHECK constraint rejects any other mix.

The row is also the lock that serializes shop creation and allowance changes
(``SELECT ... FOR UPDATE``), both in the service layer and in the
``shops_enforce_allowance`` trigger installed by migration 0009.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SINGLETON_ID = 1
LIMITED = "limited"
UNLIMITED = "unlimited"


class ShopAllowance(Base):
    __tablename__ = "shop_allowance"
    __table_args__ = (
        CheckConstraint(f"id = {SINGLETON_ID}", name="ck_shop_allowance_singleton"),
        CheckConstraint(
            f"(mode = '{LIMITED}' AND max_shops IS NOT NULL AND max_shops >= 1) OR "
            f"(mode = '{UNLIMITED}' AND max_shops IS NULL)",
            name="ck_shop_allowance_mode",
        ),
        CheckConstraint("version >= 1", name="ck_shop_allowance_version"),
    )

    id: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, default=SINGLETON_ID, server_default=text(str(SINGLETON_ID))
    )
    mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default=UNLIMITED)
    max_shops: Mapped[int | None] = mapped_column(Integer)
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
