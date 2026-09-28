from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

NOTIFICATION_CATEGORIES = [
    "orders", "payments", "shipments", "returns",
    "settlements", "ai", "procurement", "leads", "system",
]
NOTIFICATION_LEVELS = ["info", "success", "warning", "critical"]


class Notification(Base):
    """One in-app notification for one recipient (plan §39).

    The dispatcher fans domain events out per active user, honouring each
    user's per-category channel preferences. `read_at` is per-row because
    every row belongs to exactly one user.
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipient_user_id: Mapped[int] = mapped_column(Integer, index=True)
    org_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    category: Mapped[str] = mapped_column(String(30), default="system", index=True)
    level: Mapped[str] = mapped_column(String(20), default="info")  # info|success|warning|critical
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(String(1024), default="")
    entity_type: Mapped[str] = mapped_column(String(50), default="")  # e.g. "order", "purchase_order"
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_notifications_recipient_read", "recipient_user_id", "read_at"),
    )


class NotificationPreference(Base):
    """Per-user, per-category channel switches (plan §39).

    `in_app` gates the Ecos notification centre; `email` and `whatsapp` are
    wired for the outbound channel workers (Phase 3) — the dispatcher already
    respects them so flipping a switch changes behaviour, not just UI.
    """

    __tablename__ = "notification_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    category: Mapped[str] = mapped_column(String(30))
    in_app: Mapped[bool] = mapped_column(Boolean, default=True)
    email: Mapped[bool] = mapped_column(Boolean, default=False)
    whatsapp: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("user_id", "category", name="uq_notif_pref_user_category"),
    )
