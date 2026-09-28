"""Payment service — capture and refunds (plan §24-25).

Capturing a payment publishes `payment.received`, which the finance
subscriber turns into ledger entries (§26) — payments never write to the
ledger directly, keeping the domain boundary clean.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core import events
from app.orders import models as om
from app.payments import models as pm


def capture_payment(db: Session, payment: pm.Payment, *, reference: str = "") -> pm.Payment:
    if payment.status == "paid":
        return payment
    if payment.status not in ("pending", "failed"):
        raise ValueError(f"Cannot capture payment in status {payment.status}")

    payment.status = "paid"
    payment.collected_at = datetime.now(timezone.utc)
    payment.reference = reference or payment.reference or f"PAY-{payment.id:08d}"

    events.publish(db, "payment.received", {
        "payment_id": payment.id, "order_id": payment.order_id,
        "amount": payment.amount, "currency": payment.currency,
        "method": payment.method, "reference": payment.reference,
    })
    return payment


def refund_payment(db: Session, payment: pm.Payment, *, reference: str = "") -> pm.Payment:
    """Refund a captured payment — publishes `payment.refunded` so finance
    writes the money-out ledger entry (§26) and returns audit stays intact."""
    if payment.status != "paid":
        raise ValueError(f"Cannot refund payment in status {payment.status}")

    payment.status = "refunded"
    payment.reference = reference or payment.reference

    events.publish(db, "payment.refunded", {
        "payment_id": payment.id, "order_id": payment.order_id,
        "amount": -payment.amount,  # signed: money OUT of the network
        "currency": payment.currency, "method": payment.method,
        "reference": payment.reference,
    })
    return payment


def sync_order_payment_status(db: Session, order_id: int) -> None:
    order = db.get(om.Order, order_id)
    payment = db.query(pm.Payment).filter(pm.Payment.order_id == order_id).first()
    if order and payment:
        order.payment_status = "paid" if payment.status == "paid" else order.payment_status
