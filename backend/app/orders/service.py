"""Order service — creation and state transitions (plan §19-20).

Creation prices items via the pricing engine, snapshots costs, creates the
payment record, and publishes `order.created`. Transitions are validated
against the state machine and published as events so downstream domains
(fulfillment, payments, finance, automation) react declaratively.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.catalog import models as cm
from app.core import events
from app.core.pricing import price_product
from app.orders import models as m
from app.payments import models as pm


def create_order(
    db: Session,
    *,
    store_id: int,
    customer_id: int,
    product_id: int,
    qty: int = 1,
    payment_method: str = "cod",
    lead_id: int | None = None,
    delivery_fee: float = 0.0,
) -> dict:
    if qty < 1:
        raise ValueError("qty must be >= 1")
    if payment_method not in m.PAYMENT_METHODS:
        raise ValueError(f"Invalid payment method: {payment_method}")

    product = db.get(cm.Product, product_id)
    if product is None:
        raise ValueError("Unknown product")
    if product.stock < qty:
        raise ValueError(f"Insufficient stock for product {product.id}")

    breakdown = price_product(
        supplier_cost=product.supplier_cost, currency=product.currency,
        weight_kg=product.weight_kg, markup_pct=product.markup_pct,
    )
    unit_price = breakdown.ecos_price_ngn
    items_total = unit_price * qty

    order = m.Order(
        store_id=store_id, customer_id=customer_id, lead_id=lead_id,
        payment_method=payment_method, currency="NGN",
        items_total=items_total, delivery_fee=delivery_fee,
        total=items_total + delivery_fee,
    )
    db.add(order)
    db.flush()

    item = m.OrderItem(
        order_id=order.id, product_id=product.id, title=product.title,
        qty=qty, unit_price=unit_price, supplier_cost_cny=product.supplier_cost,
        weight_kg=product.weight_kg,
    )
    db.add(item)

    product.stock -= qty

    payment = pm.Payment(
        order_id=order.id, method=payment_method, status="pending",
        amount=order.total, currency="NGN",
    )
    db.add(payment)

    events.publish(db, "order.created", {
        "order_id": order.id, "store_id": store_id, "customer_id": customer_id,
        "product_id": product_id, "qty": qty, "total_ngn": order.total,
        "payment_method": payment_method, "lead_id": lead_id,
    })
    return {"id": order.id, "status": order.status, "total": order.total}


def transition_order(db: Session, order: m.Order, new_status: str, *, actor: str = "system") -> m.Order:
    allowed = m.ORDER_TRANSITIONS.get(order.status, [])
    if new_status not in allowed:
        raise ValueError(f"Illegal transition {order.status} -> {new_status}")
    old = order.status
    order.status = new_status
    events.publish(db, "order.status_changed", {
        "order_id": order.id, "from": old, "to": new_status, "actor": actor,
    })
    return order
