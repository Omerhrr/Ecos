"""Fulfillment & logistics service (plan §20-23).

Creating a shipment bridges the operator order into the supply network;
tracking events are normalized onto the Ecos timeline and cascade order
status transitions, publishing `shipment.*` events as they go.
"""

from __future__ import annotations

import secrets

from sqlalchemy.orm import Session

from app.core import events
from app.logistics import models as lm
from app.orders import models as om
from app.orders import service as order_service


def create_shipment_for_order(db: Session, order: om.Order, *, carrier: str = "Ecos Network") -> lm.Shipment:
    """Take a confirmed order into fulfillment: create the shipment and start the flow."""
    if order.status not in ("confirmed", "processing"):
        raise ValueError(f"Order {order.id} is {order.status}; must be confirmed to fulfill")

    customer = order  # customer details come via order relation below
    from app.crm.models import Customer

    cust = db.get(Customer, order.customer_id)

    if order.status == "confirmed":
        order_service.transition_order(db, order, "processing")

    shipment = lm.Shipment(
        order_id=order.id, status="processing", carrier=carrier,
        tracking_code=f"ECOS-NG-{secrets.token_hex(4).upper()}",
        recipient_name=cust.full_name if cust else "",
        recipient_phone=cust.phone if cust else "",
        recipient_address=cust.address if cust else "",
    )
    db.add(shipment)
    db.flush()

    db.add(lm.TrackingEvent(
        shipment_id=shipment.id, code="supplier_processing",
        description="Supplier received the order and is preparing it for pickup.",
        location="Origin, CN",
    ))
    events.publish(db, "shipment.created", {
        "shipment_id": shipment.id, "order_id": order.id,
        "tracking_code": shipment.tracking_code,
    })

    order_service.transition_order(db, order, "fulfilled")
    return shipment


def add_tracking_event(
    db: Session, shipment: lm.Shipment, *, code: str,
    description: str = "", location: str = "",
) -> lm.TrackingEvent:
    if code not in lm.TRACKING_CODES:
        raise ValueError(f"Unknown tracking code: {code}")

    event = lm.TrackingEvent(
        shipment_id=shipment.id, code=code, description=description, location=location
    )
    db.add(event)
    shipment.status = lm.SHIPMENT_STATUS_MAP.get(code, shipment.status)

    events.publish(db, "shipment.updated", {
        "shipment_id": shipment.id, "order_id": shipment.order_id,
        "code": code, "status": shipment.status,
    })

    order = db.get(om.Order, shipment.order_id)
    if order is not None:
        target = lm.ORDER_STATUS_MAP.get(code)
        if target and target != order.status:
            try:
                order_service.transition_order(db, order, target, actor="logistics")
            except ValueError:
                pass  # order already ahead of the tracking event; keep tracking truth

        if code == "delivered":
            from datetime import datetime, timezone

            shipment.delivered_at = datetime.now(timezone.utc)
            events.publish(db, "shipment.delivered", {
                "shipment_id": shipment.id, "order_id": order.id,
            })

    return event
