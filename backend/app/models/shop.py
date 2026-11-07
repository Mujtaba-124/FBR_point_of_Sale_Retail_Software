"""Shops: the company's operational locations (single company, many shops)."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

CODE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,19}$"
POS_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,49}$"


class Shop(Base):
    """One shop. ``id`` is permanent: future uploads, approvals and reports refer to it.

    ``encrypted_fbr_token`` holds an AES-256-GCM token under the FBR keyring
    (``app.core.secret_box.FBR``); NULL means "Token not configured". Shops are
    never deleted, only deactivated. ``version`` guards against stale edits.
    """

    __tablename__ = "shops"
    __table_args__ = (
        Index("uq_shops_code_lower", func.lower(text("code")), unique=True),
        Index("uq_shops_pos_id_lower", func.lower(text("pos_id")), unique=True),
        Index("ix_shops_is_active", "is_active"),
        CheckConstraint("length(trim(name)) > 0", name="ck_shops_name"),
        CheckConstraint("length(trim(branch_name)) > 0", name="ck_shops_branch_name"),
        CheckConstraint(f"code ~ '{CODE_PATTERN}'", name="ck_shops_code"),
        CheckConstraint(f"pos_id ~ '{POS_ID_PATTERN}'", name="ck_shops_pos_id"),
        CheckConstraint(
            "(encrypted_fbr_token IS NULL) = (fbr_token_updated_at IS NULL)",
            name="ck_shops_fbr_token_state",
        ),
        CheckConstraint(
            "sales_tax_rate IS NULL OR (sales_tax_rate >= 0 AND sales_tax_rate <= 100)",
            name="ck_shops_sales_tax_rate",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    branch_name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    pos_id: Mapped[str] = mapped_column(String(50), nullable=False)
    encrypted_fbr_token: Mapped[str | None] = mapped_column(Text)
    fbr_token_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Sales Tax % applied to new upload batches (tax exclusive). NULL = not configured
    # (shops created before Phase 4.2): no rate is ever assumed. Saved uploads keep
    # their own snapshot (upload_revisions.applied_sales_tax_rate) and never follow it.
    sales_tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
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
