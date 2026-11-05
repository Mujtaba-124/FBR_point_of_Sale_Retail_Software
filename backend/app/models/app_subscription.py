from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, SmallInteger, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SINGLETON_ID = 1


class AppSubscription(Base):
    """The single company's software subscription (this is not a multi-tenant app).

    ``id`` is fixed to 1 by a CHECK constraint, so the table can never hold
    more than one subscription record.
    """

    __tablename__ = "app_subscription"
    __table_args__ = (
        CheckConstraint(f"id = {SINGLETON_ID}", name="ck_app_subscription_singleton"),
        CheckConstraint("expiry_date >= start_date", name="ck_app_subscription_date_range"),
        CheckConstraint("length(trim(company_name)) > 0", name="ck_app_subscription_company_name"),
    )

    id: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, default=SINGLETON_ID, server_default=text(str(SINGLETON_ID))
    )
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_renewed_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
