"""AGM — Agent Management System (plan §5 participants, §20-22, §24).

Agents are the local logistics people of the destination market. A vendor
(e-commerce operator) sends their sourced stock to an agent's warehouse;
the agent stores it PER VENDOR, and when the vendor confirms a customer
order the agent gets the alert, calls the customer, ships out, collects
COD and remits.

Tables:
  AgentProfile        the agent's public face in the directory
  AgentLink           vendor <-> agent relationship (who stores for whom)
  AgentWarehouse      the agent's physical locations
  AgentStockItem      per (warehouse, vendor, product) inventory
  AgentStockMovement  signed ledger of every stock change
  AgentOrder          the fulfillment alert: call -> ship -> COD -> remit
  AgentRemittance     custody leg of COD cash (§24): collect -> remit -> reconcile
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

AGENT_ORDER_STATUSES = [
    "notified", "accepted", "calling", "confirmed", "out_for_delivery",
    "delivered", "failed", "returned", "cancelled",
]

AGENT_ORDER_TRANSITIONS: dict[str, list[str]] = {
    "notified": ["accepted", "cancelled"],
    "accepted": ["calling", "cancelled"],
    "calling": ["confirmed", "failed", "cancelled"],   # customer unreachable
    "confirmed": ["out_for_delivery"],
    "out_for_delivery": ["delivered", "failed"],
    "failed": ["out_for_delivery", "returned", "cancelled"],
    "delivered": ["returned"],
    "returned": [],
    "cancelled": [],
}

REMITTANCE_STATUSES = ["draft", "remitted", "reconciled", "cancelled"]

REMITTANCE_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["remitted", "cancelled"],
    "remitted": ["reconciled", "cancelled"],
    "reconciled": [],
    "cancelled": [],
}


class AgentProfile(Base):
    """The agent's directory card — what vendors see before they add them."""

    __tablename__ = "agent_profiles"

    org_id: Mapped[int] = mapped_column(Integer, primary_key=True)  # agent Organization.id
    contact_name: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    whatsapp: Mapped[str] = mapped_column(String(50), default="")
    city: Mapped[str] = mapped_column(String(100), default="")
    country: Mapped[str] = mapped_column(String(2), default="NG")
    address: Mapped[str] = mapped_column(String(1024), default="")
    capacity_note: Mapped[str] = mapped_column(String(500), default="")
    rating: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)  # active | suspended
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentLink(Base):
    """Vendor <-> agent relationship (§5): the agent stores and fulfils for
    this vendor. Created by the vendor ('add an agent'), visible to both."""

    __tablename__ = "agent_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_org_id: Mapped[int] = mapped_column(Integer, index=True)
    vendor_org_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)  # active | suspended
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("agent_org_id", "vendor_org_id", name="uq_agent_link_pair"),
    )


class AgentWarehouse(Base):
    """A physical location the agent runs (§22 — multi-warehouse)."""

    __tablename__ = "agent_warehouses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_org_id: Mapped[int] = mapped_column(Integer, index=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    city: Mapped[str] = mapped_column(String(100), default="")
    country: Mapped[str] = mapped_column(String(2), default="NG")
    address: Mapped[str] = mapped_column(String(1024), default="")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    is_default: Mapped[bool] = mapped_column(Integer, default=0)  # sqlite-friendly bool
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentStockItem(Base):
    """Current units of one product, in one agent warehouse, for ONE vendor.

    The vendor dimension is what makes the AGM an agent system: the same
    shelf unit can hold stock for many vendors, counted separately (§20).
    """

    __tablename__ = "agent_stock_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_org_id: Mapped[int] = mapped_column(Integer, index=True)
    warehouse_id: Mapped[int] = mapped_column(Integer, index=True)
    vendor_org_id: Mapped[int] = mapped_column(Integer, index=True)
    product_id: Mapped[int] = mapped_column(Integer, index=True)
    on_hand: Mapped[int] = mapped_column(Integer, default=0)
    reserved: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("warehouse_id", "vendor_org_id", "product_id", name="uq_agent_stock_wh_vendor_product"),
    )


class AgentStockMovement(Base):
    """Immutable AGM stock ledger row — inventory stays explainable (§22)."""

    __tablename__ = "agent_stock_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_org_id: Mapped[int] = mapped_column(Integer, index=True)
    warehouse_id: Mapped[int] = mapped_column(Integer, index=True)
    vendor_org_id: Mapped[int] = mapped_column(Integer, index=True)
    product_id: Mapped[int] = mapped_column(Integer, index=True)
    movement_type: Mapped[str] = mapped_column(String(30), index=True)
    # inbound_receive | outbound_ship | adjustment | return_in
    qty: Mapped[int] = mapped_column(Integer)  # signed
    balance_after: Mapped[int] = mapped_column(Integer, default=0)
    reference_type: Mapped[str] = mapped_column(String(50), default="")
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(String(1024), default="")
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentOrder(Base):
    """The fulfillment alert (the heart of the AGM flow):

        vendor confirms a customer order -> marks it for their agent
        -> AgentOrder(notified) + alert straight to the agent
        -> agent accepts, calls the customer, confirms, ships out
        -> delivered (COD collected at the door) / failed (retry path)
        -> remittance: the agent's cash custody is reconciled (§24)

    The agent sees customer contact + drop address — they are the last mile.
    The supplier never sees any of this (§9).
    """

    __tablename__ = "agent_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    agent_org_id: Mapped[int] = mapped_column(Integer, index=True)
    vendor_org_id: Mapped[int] = mapped_column(Integer, index=True)
    order_id: Mapped[int] = mapped_column(Integer, index=True)  # the vendor's customer order
    product_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    qty: Mapped[int] = mapped_column(Integer, default=1)
    customer_name: Mapped[str] = mapped_column(String(255), default="")
    customer_phone: Mapped[str] = mapped_column(String(50), default="")
    customer_address: Mapped[str] = mapped_column(String(1024), default="")
    customer_city: Mapped[str] = mapped_column(String(100), default="")
    payment_method: Mapped[str] = mapped_column(String(30), default="cod")
    cod_expected: Mapped[float] = mapped_column(Float, default=0.0)
    cod_collected: Mapped[float] = mapped_column(Float, default=0.0)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remittance_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="notified", index=True)
    note: Mapped[str] = mapped_column(String(1024), default="")
    failed_reason: Mapped[str] = mapped_column(String(500), default="")
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    __table_args__ = (
        Index("ix_agent_orders_queue", "agent_org_id", "status"),
    )


class AgentRemittance(Base):
    """The agent's COD custody register (§24): collected cash is the agent's
    responsibility until remitted and counted. Variance true-ups land in the
    ledger as `cod_variance` (party=agent) — same integrity rule as couriers."""

    __tablename__ = "agent_remittances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    register_code: Mapped[str] = mapped_column(String(30), unique=True)
    agent_org_id: Mapped[int] = mapped_column(Integer, index=True)
    vendor_org_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)  # null = mixed vendors
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    currency: Mapped[str] = mapped_column(String(3), default="NGN")
    expected_amount: Mapped[float] = mapped_column(Float, default=0.0)
    remitted_amount: Mapped[float] = mapped_column(Float, default=0.0)
    counted_amount: Mapped[float] = mapped_column(Float, default=0.0)
    variance_amount: Mapped[float] = mapped_column(Float, default=0.0)
    reference: Mapped[str] = mapped_column(String(120), default="")
    note: Mapped[str] = mapped_column(String(1024), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    remitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentRemittanceLine(Base):
    """One delivered-COD agent order inside a remittance register."""

    __tablename__ = "agent_remittance_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    remittance_id: Mapped[int] = mapped_column(Integer, index=True)
    agent_order_id: Mapped[int] = mapped_column(Integer, index=True)
    order_id: Mapped[int] = mapped_column(Integer, index=True)
    vendor_org_id: Mapped[int] = mapped_column(Integer, index=True)
    expected_amount: Mapped[float] = mapped_column(Float, default=0.0)
    counted_amount: Mapped[float] = mapped_column(Float, default=0.0)


# JSON re-export for API symmetry (kept here so models stay the single import)
__all__ = [
    "AGENT_ORDER_STATUSES", "AGENT_ORDER_TRANSITIONS", "REMITTANCE_STATUSES",
    "REMITTANCE_TRANSITIONS", "AgentProfile", "AgentLink", "AgentWarehouse",
    "AgentStockItem", "AgentStockMovement", "AgentOrder", "AgentRemittance",
    "AgentRemittanceLine", "JSON",
]
