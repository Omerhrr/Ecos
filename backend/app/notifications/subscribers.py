"""Domain events -> notification fan-out (plan §39 wiring).

Every handler resolves the affected org from the event payload (walking
order -> store -> org when needed), then calls `service.notify()`. A
handler that cannot resolve an org stays silent — notifications are never
allowed to break the triggering operation (the event bus already isolates
subscriber errors, but handlers are also written defensively).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core import events
from app.orders import models as om
from app.settlements import models as sm
from app.storefront import models as stm
from app.notifications import service as svc


def _org_of_order(db: Session, order_id) -> int | None:
    if order_id is None:
        return None
    order = db.get(om.Order, int(order_id))
    if not order:
        return None
    store = db.get(stm.Store, order.store_id)
    return store.org_id if store else None


def _org_of_store(db: Session, store_id) -> int | None:
    if store_id is None:
        return None
    store = db.get(stm.Store, int(store_id))
    return store.org_id if store else None


_BAD_STATUSES = {"cancelled", "failed", "returned", "refunded", "disputed"}


def _on_order_created(db: Session, p: dict) -> None:
    org = _org_of_order(db, p.get("order_id"))
    svc.notify(
        db, org_id=org, category="orders", level="info",
        title=f"New order #{p.get('order_id')} — ₦{float(p.get('total_ngn') or 0):,.0f}",
        body=f"Order placed via {'COD' if p.get('payment_method') == 'cod' else 'online transfer'} "
             f"({p.get('qty')} unit(s)). Awaiting confirmation.",
        entity_type="order", entity_id=p.get("order_id"),
    )


def _on_order_status_changed(db: Session, p: dict) -> None:
    to = p.get("to", "")
    org = _org_of_order(db, p.get("order_id"))
    if to == "delivered":
        level, verb = "success", "delivered"
    elif to in _BAD_STATUSES:
        level, verb = "warning", to.replace("_", " ")
    else:
        level, verb = "info", to.replace("_", " ")
    svc.notify(
        db, org_id=org, category="orders", level=level,
        title=f"Order #{p.get('order_id')} {verb}",
        body=f"Status moved {p.get('from')} → {to}.",
        entity_type="order", entity_id=p.get("order_id"),
    )


def _on_payment_received(db: Session, p: dict) -> None:
    org = _org_of_order(db, p.get("order_id"))
    svc.notify(
        db, org_id=org, category="payments", level="success",
        title=f"Payment received — ₦{float(p.get('amount') or 0):,.0f} on order #{p.get('order_id')}",
        body=f"Method {p.get('method')}, reference {p.get('reference') or '—'}. Ledger waterfall written.",
        entity_type="payment", entity_id=p.get("payment_id"),
    )


def _on_payment_refunded(db: Session, p: dict) -> None:
    org = _org_of_order(db, p.get("order_id"))
    svc.notify(
        db, org_id=org, category="payments", level="warning",
        title=f"Refund issued — ₦{abs(float(p.get('amount') or 0)):,.0f} on order #{p.get('order_id')}",
        body=f"Reference {p.get('reference') or '—'}. Money-out ledger entry written.",
        entity_type="payment", entity_id=p.get("payment_id"),
    )


def _on_payment_voided(db: Session, p: dict) -> None:
    org = _org_of_order(db, p.get("order_id"))
    svc.notify(
        db, org_id=org, category="payments", level="warning",
        title=f"Payment voided on order #{p.get('order_id')}",
        body=f"Nothing was collected ({p.get('rma_number') or 'no RMA'}); payment closed without refund.",
        entity_type="payment", entity_id=p.get("payment_id"),
    )


def _on_shipment_delivered(db: Session, p: dict) -> None:
    org = _org_of_order(db, p.get("order_id"))
    svc.notify(
        db, org_id=org, category="shipments", level="success",
        title=f"Shipment delivered — order #{p.get('order_id')}",
        body=f"Tracking code {p.get('tracking_code') or '—'} completed its journey.",
        entity_type="shipment", entity_id=p.get("shipment_id"),
    )


def _on_return_requested(db: Session, p: dict) -> None:
    org = _org_of_store(db, p.get("store_id"))
    svc.notify(
        db, org_id=org, category="returns", level="warning",
        title=f"{p.get('rma_number')} requested on order #{p.get('order_id')}",
        body=f"Reason: {p.get('reason')}, resolution: {p.get('resolution')} "
             f"(₦{float(p.get('refund_amount') or 0):,.0f}). Review it in Returns.",
        entity_type="return", entity_id=p.get("rma_id"),
    )


def _on_return_status_changed(db: Session, p: dict) -> None:
    org = _org_of_order(db, p.get("order_id"))
    to = p.get("to", "")
    level = "success" if to in {"refunded", "closed"} else "info"
    svc.notify(
        db, org_id=org, category="returns", level=level,
        title=f"{p.get('rma_number')} → {to.replace('_', ' ')}",
        body=f"RMA moved {p.get('from')} → {to}.",
        entity_type="return", entity_id=p.get("rma_id"),
    )


def _on_settlement_completed(db: Session, p: dict) -> None:
    run = db.get(sm.SettlementRun, p.get("run_id")) if p.get("run_id") else None
    svc.notify(
        db, org_id=run.org_id if run else None, category="settlements", level="success",
        title=f"Settlement {p.get('run_number')} executed",
        body=f"{p.get('line_count')} line(s), {p.get('entry_count')} ledger entries settled "
             f"— ₦{abs(float(p.get('total_amount') or 0)):,.0f} {p.get('currency')}.",
        entity_type="settlement_run", entity_id=p.get("run_id"),
    )


def _org_of_ai_run(db: Session, run_id) -> int | None:
    if run_id is None:
        return None
    from app.ai_harness import models as aim

    run = db.get(aim.AiRun, int(run_id))
    if not run:
        return None
    operator = db.get(aim.AiOperator, run.operator_id)
    return operator.org_id if operator else None


def _on_ai_run_failed(db: Session, p: dict) -> None:
    svc.notify(
        db, org_id=_org_of_ai_run(db, p.get("run_id")), category="ai", level="critical",
        title=f"{p.get('operator') or 'AI operator'} run failed",
        body=(p.get("error") or "Unknown error")[:300],
        entity_type="ai_run", entity_id=p.get("run_id"),
    )


def _on_ai_proposal_approved(db: Session, p: dict) -> None:
    svc.notify(
        db, org_id=_org_of_ai_run(db, p.get("run_id")), category="ai", level="success",
        title=f"{p.get('operator') or 'AI operator'} proposal applied",
        body="An approved AI proposal executed its side effect.",
        entity_type="ai_run", entity_id=p.get("run_id"),
    )


def _on_reorder_suggested(db: Session, p: dict) -> None:
    org_id = p.get("org_id")
    svc.notify(
        db, org_id=org_id, category="procurement", level="warning",
        title=f"Stock Prophet: {p.get('open_count')} restock suggestion(s) open",
        body=f"{p.get('fresh_count')} new suggestion(s) from the latest run — "
             f"review them in Procurement and raise POs.",
        entity_type="ai_run", entity_id=p.get("run_id"),
    )


def _on_po_created(db: Session, p: dict) -> None:
    org_id = p.get("org_id")
    svc.notify(
        db, org_id=org_id, category="procurement", level="info",
        title=f"PO {p.get('po_number')} raised to {p.get('supplier_name')}",
        body=f"{p.get('line_count')} line(s), {p.get('units')} units — "
             f"¥{float(p.get('items_total') or 0):,.2f}. Source: {p.get('source')}.",
        entity_type="purchase_order", entity_id=p.get("po_id"),
    )


def _on_po_received(db: Session, p: dict) -> None:
    org_id = p.get("org_id")
    svc.notify(
        db, org_id=org_id, category="procurement", level="success",
        title=f"PO {p.get('po_number')} fully received",
        body=f"{p.get('units')} units added to stock — goods receipt complete.",
        entity_type="purchase_order", entity_id=p.get("po_id"),
    )


def _on_po_cancelled(db: Session, p: dict) -> None:
    org_id = p.get("org_id")
    svc.notify(
        db, org_id=org_id, category="procurement", level="warning",
        title=f"PO {p.get('po_number')} cancelled",
        body="Linked reorder suggestions (if any) were reopened.",
        entity_type="purchase_order", entity_id=p.get("po_id"),
    )


def register() -> None:
    events.subscribe("order.created", _on_order_created)
    events.subscribe("order.status_changed", _on_order_status_changed)
    events.subscribe("payment.received", _on_payment_received)
    events.subscribe("payment.refunded", _on_payment_refunded)
    events.subscribe("payment.voided", _on_payment_voided)
    events.subscribe("shipment.delivered", _on_shipment_delivered)
    events.subscribe("return.requested", _on_return_requested)
    events.subscribe("return.status_changed", _on_return_status_changed)
    events.subscribe("settlement.completed", _on_settlement_completed)
    events.subscribe("ai.run.failed", _on_ai_run_failed)
    events.subscribe("ai.proposal.approved", _on_ai_proposal_approved)
    events.subscribe("reorder.suggested", _on_reorder_suggested)
    events.subscribe("procurement.po_created", _on_po_created)
    events.subscribe("procurement.po_received", _on_po_received)
    events.subscribe("procurement.po_cancelled", _on_po_cancelled)
