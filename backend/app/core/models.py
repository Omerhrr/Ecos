from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DomainEvent(Base):
    """Append-only log of domain events (plan §40 — event-driven architecture).

    Every meaningful state change in the system publishes an event here.
    This log doubles as the audit trail and as the input feed for the
    future automation engine (§41) and AI harness (§31).
    """

    __tablename__ = "domain_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (Index("ix_domain_events_name_id", "name", "id"),)
