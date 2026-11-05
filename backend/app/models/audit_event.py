import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditEvent(Base):
    """Append-only security audit trail.

    Rows are only ever inserted. ``target_user_id`` deliberately has no foreign
    key so the trail survives if the referenced row ever changes. ``details``
    must never contain passwords, hashes or tokens.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_target_user_id", "target_user_id"),
        Index("ix_audit_events_occurred_at", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
