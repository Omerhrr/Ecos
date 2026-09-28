from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

PO_STATUSES = ["draft", "submitted", "confirmed", "received", "cancelled"]

PO_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["submitted", "cancelled"],
    "submitted": ["confirmed", "cancelled"],
    "confirmed": ["received", "cancelled"],  # "received" is set by goods receipt
    "received": [],
    "cancelled": [],
}

# goods receipt posts stock against confirmed POs (partial receives keep it confirmed)
RECEIVABLE_STATUSES = ["confirmed"]

SUGGESTION_STATUSES = ["open", "converted", "dismissed", "superseded"]


class PurchaseOrder(Base):
    """A purchase order to a supplier (plan §21-22, supply side).

    Procurement converts Stock Prophet's reorder suggestions (§33 demand
    forecaster) into explicit, approvable POs. POs live in the supplier's
    cost currency (CNY on this corridor). Receiving a line adds the units
    back into product stock — the demand signal that started the loop.

    Lifecycle:  draft -> submitted -> confirmed -> received   (cancel exits)
    """

    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    po_number: Mapped[str] = mapped_column(String(30), unique=True)
    supplier_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    items_total: Mapped[float] = mapped_column(Float, default=0.0)
    freight: Mapped[float] = mapped_column(Float, default=0.0)
    expected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(String(1024), default="")
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | stock_prophet
    source_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    org_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PurchaseOrderLine(Base):
    """One product line on a PO; `unit_cost` snapshots the supplier cost."""

    __tablename__ = "purchase_order_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    po_id: Mapped[int] = mapped_column(Integer, index=True)
    product_id: Mapped[int] = mapped_column(Integer, index=True)
    qty_ordered: Mapped[int] = mapped_column(Integer, default=0)
    qty_received: Mapped[int] = mapped_column(Integer, default=0)
    unit_cost: Mapped[float] = mapped_column(Float, default=0.0)  # in PO currency


class ReorderSuggestion(Base):
    """One actionable Stock Prophet recommendation (§33 -> §21 bridge).

    The harness's demand forecaster is advisory — it mutates nothing. When
    its run completes, this table materialises the suggested reorders as
    first-class objects procurement can convert (`converted`), dismiss, or
    silently replace when a fresher run lands (`superseded`).
    """

    __tablename__ = "reorder_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(Integer, index=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    org_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    risk: Mapped[str] = mapped_column(String(20), default="watch")  # stockout|watch|healthy
    weekly_velocity: Mapped[float] = mapped_column(Float, default=0.0)
    weeks_of_cover: Mapped[float | None] = mapped_column(Float, nullable=True)
    stock_at_time: Mapped[int] = mapped_column(Integer, default=0)
    suggested_qty: Mapped[int] = mapped_column(Integer, default=0)
    po_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("run_id", "product_id", name="uq_suggestion_run_product"),
    )
