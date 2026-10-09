from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Normalized tracking timeline (plan §23) — external providers are mapped onto these codes
TRACKING_CODES = [
    "supplier_processing", "picked_up", "origin_warehouse", "exported",
    "in_transit", "customs", "destination_hub", "local_courier",
    "out_for_delivery", "delivered",
    # reverse logistics (§21, §28)
    "return_requested", "return_pickup", "return_received",
]

# tracking code -> shipment status
SHIPMENT_STATUS_MAP = {
    "supplier_processing": "processing",
    "picked_up": "in_transit",
    "origin_warehouse": "in_transit",
    "exported": "in_transit",
    "in_transit": "in_transit",
    "customs": "in_transit",
    "destination_hub": "in_transit",
    "local_courier": "in_transit",
    "out_for_delivery": "out_for_delivery",
    "delivered": "delivered",
    "return_requested": "return_pending",
    "return_pickup": "returning",
    "return_received": "returned",
}

# tracking code -> order status progression (plan §19 lifecycle)
ORDER_STATUS_MAP = {
    "supplier_processing": "processing",
    "picked_up": "in_transit",
    "origin_warehouse": "in_transit",
    "exported": "in_transit",
    "in_transit": "in_transit",
    "customs": "in_transit",
    "destination_hub": "in_transit",
    "local_courier": "in_transit",
    "out_for_delivery": "out_for_delivery",
    "delivered": "delivered",
}


class Shipment(Base):
    """A shipment moving through the logistics network (plan §21-22)."""

    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(30), default="processing", index=True)
    carrier: Mapped[str] = mapped_column(String(255), default="Ecos Network")
    tracking_code: Mapped[str] = mapped_column(String(50), unique=True)
    origin_country: Mapped[str] = mapped_column(String(2), default="CN")
    destination_country: Mapped[str] = mapped_column(String(2), default="NG")
    recipient_name: Mapped[str] = mapped_column(String(255), default="")
    recipient_phone: Mapped[str] = mapped_column(String(50), default="")
    recipient_address: Mapped[str] = mapped_column(String(1024), default="")
    weight_kg: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TrackingEvent(Base):
    """One normalized checkpoint on the unified tracking timeline."""

    __tablename__ = "tracking_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(Integer, index=True)
    code: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(String(1024), default="")
    location: Mapped[str] = mapped_column(String(255), default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


FREIGHT_MODES = ["air", "sea", "express", "road"]


class FreightRateCard(Base):
    """A purchasable freight option on a corridor (plan §21, §57).

    The waterfall used one hardcoded per-kg rate; real corridors price by
    MODE (air vs sea), with a fixed handling base, fuel surcharges and a
    customs share of declared value. Cards are data: resolution picks the
    best active card for (origin, dest, mode) — cheapest effective per-kg
    when mode is open — and the waterfall falls back to the profile's flat
    per-kg when nothing matches.
    """

    __tablename__ = "freight_rate_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)  # NULL = platform card
    name: Mapped[str] = mapped_column(String(120))
    mode: Mapped[str] = mapped_column(String(20), default="air", index=True)
    origin_country: Mapped[str] = mapped_column(String(2), default="CN")
    dest_country: Mapped[str] = mapped_column(String(2), default="NG")
    base_fixed_ngn: Mapped[float] = mapped_column(Float, default=0.0)   # handling/documentation
    per_kg_ngn: Mapped[float] = mapped_column(Float)                    # headline rate
    fuel_surcharge_pct: Mapped[float] = mapped_column(Float, default=0.0)
    customs_pct: Mapped[float] = mapped_column(Float, default=0.0)      # of declared (supplier) value
    min_charge_ngn: Mapped[float] = mapped_column(Float, default=0.0)
    lead_time_days_min: Mapped[int] = mapped_column(Integer, default=7)
    lead_time_days_max: Mapped[int] = mapped_column(Integer, default=14)
    active: Mapped[int] = mapped_column(Integer, default=1)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
