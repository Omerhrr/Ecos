from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

ORDER_STATUSES = [
    "draft", "pending_confirmation", "confirmed", "processing", "fulfilled",
    "in_transit", "out_for_delivery", "delivered", "cancelled", "failed",
    "returned", "refunded",
]

# Legal transitions of the order state machine (plan §19)
ORDER_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["pending_confirmation", "cancelled"],
    "pending_confirmation": ["confirmed", "cancelled"],
    "confirmed": ["processing", "cancelled"],
    "processing": ["fulfilled", "failed"],
    "fulfilled": ["in_transit", "returned"],
    "in_transit": ["out_for_delivery", "returned"],
    "out_for_delivery": ["delivered", "failed", "returned"],
    "delivered": ["returned"],
    "failed": ["in_transit", "returned", "cancelled"],
    "returned": ["refunded"],
    "cancelled": [],
    "refunded": [],
}

PAYMENT_METHODS = ["cod", "online_transfer", "card"]


class Order(Base):
    """The central operational object connecting the system (plan §19)."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, index=True)
    customer_id: Mapped[int] = mapped_column(Integer, index=True)
    lead_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending_confirmation", index=True)
    payment_method: Mapped[str] = mapped_column(String(30), default="cod")
    payment_status: Mapped[str] = mapped_column(String(30), default="pending")  # pending | paid | refunded | failed
    currency: Mapped[str] = mapped_column(String(3), default="NGN")
    items_total: Mapped[float] = mapped_column(Float, default=0.0)
    delivery_fee: Mapped[float] = mapped_column(Float, default=0.0)
    total: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


class OrderItem(Base):
    """Line item with pricing snapshots — history must not drift with catalog changes."""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, index=True)
    product_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(255))
    qty: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[float] = mapped_column(Float)  # NGN snapshot at order time
    supplier_cost_cny: Mapped[float] = mapped_column(Float)  # CNY snapshot for finance
    weight_kg: Mapped[float] = mapped_column(Float, default=0.5)  # snapshot for logistics economics
