from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

LEAD_STATUSES = [
    "new", "contacted", "interested",
    "order_created", "confirmed", "fulfilled", "delivered",
    "unreachable", "cancelled", "returned", "refunded",
]

LEAD_SOURCES = ["meta_ads", "google_ads", "organic", "whatsapp", "referral", "tiktok"]


class Customer(Base):
    """An end customer of an operator store (plan §17-18)."""

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(50), index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str] = mapped_column(String(1024), default="")
    city: Mapped[str] = mapped_column(String(100), default="")
    state: Mapped[str] = mapped_column(String(100), default="")
    country: Mapped[str] = mapped_column(String(2), default="NG")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Lead(Base):
    """A CRM lead moving through the e-commerce pipeline (plan §17).

    New -> Contacted -> Interested -> Order Created -> Confirmed -> ... -> Delivered
    with side exits (unreachable / cancelled / returned / refunded).
    """

    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, index=True)
    product_id: Mapped[int] = mapped_column(Integer, index=True)
    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contact_name: Mapped[str] = mapped_column(String(255))
    contact_phone: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)
    source: Mapped[str] = mapped_column(String(30), default="organic")
    campaign: Mapped[str] = mapped_column(String(255), default="")
    assigned_agent: Mapped[str] = mapped_column(String(255), default="")
    notes: Mapped[str] = mapped_column(String(2048), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
