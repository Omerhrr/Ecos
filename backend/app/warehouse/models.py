from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

WAREHOUSE_STATUSES = ["active", "inactive"]

# Signed movement types — receipt/restock are positive, pick/transfer_out negative
MOVEMENT_TYPES = [
    "receipt",         # PO goods receipt putaway (§22 x §21)
    "pick",            # order fulfillment pick wave
    "adjustment",      # cycle-count correction (signed)
    "transfer_in",     # inbound leg of an inter-warehouse transfer
    "transfer_out",    # outbound leg of an inter-warehouse transfer
    "return_restock",  # stock returned after a wave cancel
]

PICK_WAVE_STATUSES = ["open", "picking", "packed", "completed", "cancelled"]

WAVE_TRANSITIONS: dict[str, list[str]] = {
    "open": ["picking", "cancelled"],
    "picking": ["packed", "cancelled"],
    "packed": ["completed", "cancelled"],
    "completed": [],
    "cancelled": [],
}

PICK_LINE_STATUSES = ["pending", "picked", "packed"]


class Warehouse(Base):
    """A physical fulfillment location on the operator side (plan §22).

    Warehouses are where procurement receipts are put away and customer
    orders are picked from. `is_default` marks the fallback receiving
    warehouse for an org (goods receipts without an explicit target land
    here).
    """

    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    city: Mapped[str] = mapped_column(String(100), default="")
    country: Mapped[str] = mapped_column(String(2), default="NG")
    address: Mapped[str] = mapped_column(String(1024), default="")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StockItem(Base):
    """Current quantity of one product inside one warehouse (plan §22).

    `on_hand` is the physical count; `reserved` is committed to pick waves
    that are still in flight. Sellable-at-this-warehouse = on_hand - reserved.
    The network-level `product.stock` remains the oversell guard for the
    storefront; this table is the per-location truth behind it.
    """

    __tablename__ = "stock_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(Integer, index=True)
    product_id: Mapped[int] = mapped_column(Integer, index=True)
    on_hand: Mapped[int] = mapped_column(Integer, default=0)
    reserved: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("warehouse_id", "product_id", name="uq_stock_item_wh_product"),
    )


class StockMovement(Base):
    """Immutable stock ledger row (plan §22 auditability).

    Every quantity change inside a warehouse is one signed row pointing at
    its business source (PO, order, adjustment, transfer, wave cancel) —
    stock levels are always explainable by replaying this ledger.
    """

    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(Integer, index=True)
    product_id: Mapped[int] = mapped_column(Integer, index=True)
    movement_type: Mapped[str] = mapped_column(String(30), index=True)
    qty: Mapped[int] = mapped_column(Integer)  # signed: +in / -out
    balance_after: Mapped[int] = mapped_column(Integer, default=0)
    reference_type: Mapped[str] = mapped_column(String(50), default="")  # purchase_order|order|adjustment|transfer|wave
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(String(1024), default="")
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_stock_movements_product_created", "product_id", "created_at"),
    )


class PickWave(Base):
    """A batch of customer orders picked together in one warehouse (§22).

    Lifecycle:  open -> picking -> packed -> completed   (cancel exits)
    Completing the wave hands every order to logistics: a shipment is
    created (if none exists yet) and the order advances to `fulfilled`.
    """

    __tablename__ = "pick_waves"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wave_number: Mapped[str] = mapped_column(String(30), unique=True)
    warehouse_id: Mapped[int] = mapped_column(Integer, index=True)
    org_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    order_count: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(String(1024), default="")
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    picked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    packed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PickLine(Base):
    """One order line inside a pick wave — the warehouse work unit."""

    __tablename__ = "pick_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wave_id: Mapped[int] = mapped_column(Integer, index=True)
    order_id: Mapped[int] = mapped_column(Integer, index=True)
    product_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(255), default="")  # snapshot at wave time
    qty: Mapped[int] = mapped_column(Integer, default=1)
    picked_qty: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")
