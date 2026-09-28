from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

PAYMENT_METHODS = ["cod", "online_transfer", "card"]
PAYMENT_STATUSES = ["pending", "paid", "failed", "refunded"]


class Payment(Base):
    """A payment against an order (plan §25).

    Method `cod` represents Cash on Delivery, a first-class capability in
    COD markets (plan §24): expected amount is tracked, collection happens
    at delivery, then reconciliation and settlement follow.
    """

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, index=True)
    method: Mapped[str] = mapped_column(String(30), default="cod")
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="NGN")
    provider: Mapped[str] = mapped_column(String(100), default="ecos_internal")
    reference: Mapped[str] = mapped_column(String(100), default="")
    reconciled: Mapped[bool] = mapped_column(Integer, default=0)  # sqlite-friendly bool
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
