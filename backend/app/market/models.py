"""Market domain — the Marketstore + sourcing orders + supplier portal.

This is the heart of the corridor model the plan describes (§1, §6, §8-11):

    Supplier (CN or any origin country)
        uploads products  ->  Luxeen review gate (§8 verification)
        -> published to the MARKETSTORE
    Operator (NG or any destination)
        browses in local currency (§46) — supplier identity fully hidden (§9)
        buys  ->  SOURCING ORDER (prepaid)  ->  routed to the supplier
    Supplier
        processes, ships, updates tracking checkpoints (§23 ladder)
    Arrival
        -> received into an AGM agent warehouse (per-vendor stock) or the
           operator's own warehouse (§22)

Isolation is enforced in the serializers, not the views: the operator
payload never carries supplier identity or economics; the supplier payload
never carries the buyer's identity — only the destination they must ship to.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

SUPPLIER_PRODUCT_STATUSES = [
    "draft", "submitted", "approved", "rejected", "published", "archived",
]

SUPPLIER_PRODUCT_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["submitted", "archived"],
    "submitted": ["approved", "rejected", "draft"],  # review gate (§8)
    "approved": ["published", "rejected"],
    "rejected": ["draft"],       # supplier edits and resubmits
    "published": ["archived"],
    "archived": [],
}

SOURCING_STATUSES = [
    "pending_payment", "paid", "processing", "shipped", "in_transit",
    "customs", "destination_hub", "arrived", "received", "cancelled",
]

SOURCING_TRANSITIONS: dict[str, list[str]] = {
    "pending_payment": ["paid", "cancelled"],
    "paid": ["processing", "cancelled"],
    "processing": ["shipped", "cancelled"],
    "shipped": ["in_transit"],
    "in_transit": ["customs", "destination_hub", "arrived"],
    "customs": ["in_transit", "destination_hub", "arrived"],
    "destination_hub": ["arrived"],
    "arrived": ["received"],
    "received": [],
    "cancelled": [],
}

# tracking code -> sourcing status (subset of the §23 normalized ladder;
# `delivered` here means "arrived at the destination in Nigeria")
SOURCING_CODE_MAP = {
    "supplier_processing": "processing",
    "picked_up": "shipped",
    "origin_warehouse": "in_transit",
    "exported": "in_transit",
    "in_transit": "in_transit",
    "customs": "customs",
    "destination_hub": "destination_hub",
    "delivered": "arrived",
}


class SupplierProduct(Base):
    """A product a supplier uploads to Ecos (plan §8, §10).

    Lifecycle:  draft -> submitted -> (Luxeen review: approved|rejected)
                -> published (creates the canonical catalog Product and the
                Marketstore listing)  — archived exits.

    This row is the SUPPLIER-SIDE truth (their cost, their specs). The
    catalog Product it materialises is the operator-facing Ecos product;
    the link stays so the corridor is traceable (§51).
    """

    __tablename__ = "supplier_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int] = mapped_column(Integer, index=True)
    org_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)  # supplier org (portal tenancy)
    title: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str] = mapped_column(String(4096), default="")
    category: Mapped[str] = mapped_column(String(100), default="general", index=True)
    industry: Mapped[str] = mapped_column(String(100), default="")  # wide range of industries (§1)
    cost_price: Mapped[float] = mapped_column(Float)  # supplier price in `currency`
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    weight_kg: Mapped[float] = mapped_column(Float, default=0.5)
    moq: Mapped[int] = mapped_column(Integer, default=1)  # minimum order quantity
    images: Mapped[list] = mapped_column(JSON, default=list)
    specs: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    review_notes: Mapped[str] = mapped_column(String(1024), default="")
    catalog_product_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


class SourcingOrder(Base):
    """An operator's prepaid purchase from the Marketstore (plan §11, §20).

    The operator sees: product, qty, local-currency total, status, tracking.
    The supplier sees: what to prepare and where to ship it — never who
    bought it (§9). Ecos sits in the middle and holds the economics.

    Lifecycle:  pending_payment -> paid -> processing (supplier accepted)
                -> shipped -> in_transit -> customs -> destination_hub
                -> arrived -> received (AGM putaway or operator warehouse)
    """

    __tablename__ = "sourcing_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_number: Mapped[str] = mapped_column(String(30), unique=True)
    org_id: Mapped[int] = mapped_column(Integer, index=True)  # buyer operator org
    supplier_id: Mapped[int] = mapped_column(Integer, index=True)  # hidden from operator payloads
    supplier_product_id: Mapped[int] = mapped_column(Integer, index=True)
    catalog_product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(255))  # snapshot
    unit_cost_cny: Mapped[float] = mapped_column(Float)
    qty: Mapped[int] = mapped_column(Integer, default=1)
    cny_total: Mapped[float] = mapped_column(Float, default=0.0)
    fx_rate: Mapped[float] = mapped_column(Float, default=0.0)  # CNY -> local snapshot (§46)
    local_currency: Mapped[str] = mapped_column(String(3), default="NGN")
    local_total: Mapped[float] = mapped_column(Float, default=0.0)
    weight_kg: Mapped[float] = mapped_column(Float, default=0.5)  # per unit snapshot
    status: Mapped[str] = mapped_column(String(30), default="pending_payment", index=True)
    payment_method: Mapped[str] = mapped_column(String(30), default="wallet")
    payment_reference: Mapped[str] = mapped_column(String(100), default="")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # destination: an AGM agent location, or the operator's own address
    agent_org_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    dest_name: Mapped[str] = mapped_column(String(255), default="")
    dest_phone: Mapped[str] = mapped_column(String(50), default="")
    dest_address: Mapped[str] = mapped_column(String(1024), default="")
    dest_city: Mapped[str] = mapped_column(String(100), default="")
    dest_country: Mapped[str] = mapped_column(String(2), default="NG")
    supplier_note: Mapped[str] = mapped_column(String(1024), default="")  # buyer -> supplier (no identity)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


class SourcingEvent(Base):
    """One normalized checkpoint on a sourcing order's inbound timeline (§23)."""

    __tablename__ = "sourcing_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sourcing_order_id: Mapped[int] = mapped_column(Integer, index=True)
    code: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(String(1024), default="")
    location: Mapped[str] = mapped_column(String(255), default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
