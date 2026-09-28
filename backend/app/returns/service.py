"""Returns service (plan §28).

The RMA state machine is deliberately narrow:

    requested -> approved  -> received -> refunded
                    |            `-> closed (replacement / store credit)
                    `-> rejected

Side effects are event-driven and stay inside each domain's boundary:
- `mark_received`    transitions the ORDER to `returned` and restocks items
- `refund`           asks payments to refund, which publishes
                     `payment.refunded`, which the finance subscriber turns
                     into the immutable ledger money-out entry (§26)
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.catalog import models as cm
from app.core import events
from app.orders import models as om
from app.orders import service as order_service
from app.payments import models as pm
from app.payments import service as payment_service
from app.returns import models as m


def create_return(
    db: Session,
    *,
    order: om.Order,
    reason: str = "other",
    resolution: str = "refund",
    restock: bool = True,
    notes: str = "",
) -> m.ReturnOrder:
    if order.status not in m.RETURNABLE_ORDER_STATUSES:
        raise ValueError(f"Order #{order.id} (status={order.status}) is not returnable")
    if reason not in m.RETURN_REASONS:
        raise ValueError(f"Invalid return reason: {reason}")
    if resolution not in m.RETURN_RESOLUTIONS:
        raise ValueError(f"Invalid resolution: {resolution}")
    open_rma = (
        db.query(m.ReturnOrder)
        .filter(
            m.ReturnOrder.order_id == order.id,
            m.ReturnOrder.status.in_(["requested", "approved", "received"]),
        )
        .first()
    )
    if open_rma:
        raise ValueError(f"Order #{order.id} already has open RMA {open_rma.rma_number}")

    rma = m.ReturnOrder(
        rma_number="pending",  # placeholder until we have the id
        order_id=order.id, store_id=order.store_id, customer_id=order.customer_id,
        reason=reason, resolution=resolution, restock=int(restock),
        refund_amount=order.total, currency=order.currency, notes=notes,
    )
    db.add(rma)
    db.flush()
    rma.rma_number = f"RMA-{rma.id:05d}"

    events.publish(db, "return.requested", {
        "rma_id": rma.id, "rma_number": rma.rma_number, "order_id": order.id,
        "store_id": order.store_id, "customer_id": order.customer_id,
        "reason": reason, "resolution": resolution, "refund_amount": rma.refund_amount,
    })
    return rma


def _transition(db: Session, rma: m.ReturnOrder, new_status: str) -> None:
    allowed = m.RETURN_TRANSITIONS.get(rma.status, [])
    if new_status not in allowed:
        raise ValueError(f"Illegal return transition {rma.status} -> {new_status}")
    old = rma.status
    rma.status = new_status
    events.publish(db, "return.status_changed", {
        "rma_id": rma.id, "rma_number": rma.rma_number,
        "order_id": rma.order_id, "from": old, "to": new_status,
    })


def approve(db: Session, rma: m.ReturnOrder) -> m.ReturnOrder:
    _transition(db, rma, "approved")
    return rma


def reject(db: Session, rma: m.ReturnOrder, *, note: str = "") -> m.ReturnOrder:
    if note:
        rma.notes = (rma.notes + f"\n[rejected] {note}").strip()
    _transition(db, rma, "rejected")
    return rma


def mark_received(db: Session, rma: m.ReturnOrder) -> m.ReturnOrder:
    """Goods are back: flip the order to `returned` and optionally restock."""
    order = db.get(om.Order, rma.order_id)
    if order is None:
        raise ValueError(f"Order {rma.order_id} not found")
    if order.status not in m.RETURNABLE_ORDER_STATUSES:
        raise ValueError(f"Order #{order.id} is in status {order.status}; expected one of {m.RETURNABLE_ORDER_STATUSES}")
    order_service.transition_order(db, order, "returned", actor="returns")

    if rma.restock:
        for item in db.query(om.OrderItem).filter(om.OrderItem.order_id == order.id).all():
            product = db.get(cm.Product, item.product_id)
            if product:
                product.stock += item.qty

    _transition(db, rma, "received")
    return rma


def refund(db: Session, rma: m.ReturnOrder) -> m.ReturnOrder:
    """Money back to the customer — ledger entry lands via `payment.refunded`."""
    order = db.get(om.Order, rma.order_id)
    if order is None:
        raise ValueError(f"Order {rma.order_id} not found")
    payment = db.query(pm.Payment).filter(pm.Payment.order_id == order.id).first()

    if payment and payment.status == "paid":
        payment_service.refund_payment(db, payment, reference=rma.rma_number)
        order.payment_status = "refunded"
        rma.refund_amount = payment.amount
    elif payment and payment.status == "pending":
        # nothing was ever collected (e.g. COD returned unopened) — just void it
        payment.status = "refunded"
        rma.refund_amount = 0.0
        events.publish(db, "payment.voided", {
            "payment_id": payment.id, "order_id": order.id, "rma_number": rma.rma_number,
        })
    else:
        rma.refund_amount = 0.0

    if order.status != "returned":
        order_service.transition_order(db, order, "returned", actor="returns")
    order_service.transition_order(db, order, "refunded", actor="returns")

    _transition(db, rma, "refunded")
    return rma


def close(db: Session, rma: m.ReturnOrder) -> m.ReturnOrder:
    """Resolve without a refund (replacement shipped, store credit granted...)."""
    _transition(db, rma, "closed")
    return rma
