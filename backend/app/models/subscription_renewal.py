import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user import User


class SubscriptionRenewal(Base):
    """Append-only history of subscription renewals.

    A database trigger rejects UPDATE and DELETE, so history cannot be
    rewritten or silently removed by the application.
    """

    __tablename__ = "subscription_renewals"
    __table_args__ = (
        CheckConstraint(
            "new_expiry_date > previous_expiry_date", name="ck_subscription_renewals_extends"
        ),
        Index("ix_subscription_renewals_renewed_at", "renewed_at"),
        Index("ix_subscription_renewals_subscription_id", "subscription_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    subscription_id: Mapped[int] = mapped_column(
        SmallInteger, ForeignKey("app_subscription.id", ondelete="RESTRICT"), nullable=False
    )
    previous_expiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    new_expiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    renewed_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    renewal_note: Mapped[str | None] = mapped_column(String(500))
    # Client-generated key: replaying the same request returns the same renewal.
    idempotency_key: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True
    )
    renewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    renewed_by: Mapped[User] = relationship(lazy="joined")
