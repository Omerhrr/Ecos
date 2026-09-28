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
