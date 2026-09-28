from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

RETURN_STATUSES = [
    "requested",   # customer asked for a return (RMA opened)
    "approved",    # operator approved; awaiting the goods
    "received",    # goods received back at the hub / inspected
    "rejected",    # request denied (outside window, used item, ...)
    "refunded",    # money returned to the customer
    "closed",      # resolved without refund (replacement / store credit handled offline)
]

RETURN_TRANSITIONS: dict[str, list[str]] = {
    "requested": ["approved", "rejected"],
    "approved": ["received", "rejected"],
    "received": ["refunded", "closed"],
    "rejected": [],
    "refunded": [],
    "closed": [],
}

RETURN_RESOLUTIONS = ["refund", "replacement", "store_credit"]

RETURN_REASONS = [
    "defective", "not_as_described", "wrong_item", "damaged_in_transit",
    "changed_mind", "late_delivery", "other",
]

# order statuses from which a return may be opened (plan §28: post-delivery,
# plus in-flight returns handled as intercept where the corridor allows it)
RETURNABLE_ORDER_STATUSES = ["fulfilled", "in_transit", "out_for_delivery", "delivered"]


class ReturnOrder(Base):
    """An RMA against an order (plan §28).

    The return follows its own state machine and drives the order state
    machine (`returned`, then `refunded`) and the finance ledger (refund
    money-out entry) through domain events — never by direct writes.
    """

    __tablename__ = "return_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rma_number: Mapped[str] = mapped_column(String(30), unique=True)
    order_id: Mapped[int] = mapped_column(Integer, index=True)
    store_id: Mapped[int] = mapped_column(Integer, index=True)
    customer_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(20), default="requested", index=True)
    reason: Mapped[str] = mapped_column(String(30), default="other")
    resolution: Mapped[str] = mapped_column(String(20), default="refund")
    restock: Mapped[int] = mapped_column(Integer, default=1)  # sqlite-friendly bool
    refund_amount: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(3), default="NGN")
    notes: Mapped[str] = mapped_column(String(2048), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
