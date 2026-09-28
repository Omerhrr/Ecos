"""Settlements service (plan §27).

Obligations are never stored as mutable balances — they are derived from
the immutable ledger (§26). A settlement run:

1. BUILDS  — scans unsettled payable entries (amount < 0, no run yet)
             and buckets them by (entry_type, party, resolved counterparty,
             currency).
2. APPROVES — a finance approver signs off the batch (governance).
3. EXECUTES — marks every underlying ledger entry as settled and publishes
             `settlement.completed`, which downstream domains (notifications,
             payouts, analytics) can consume.

Counterparty resolution turns the generic ledger `party` into a concrete
entity by walking order -> items -> product -> supplier (and store -> org
for the operator), so payouts name who actually gets paid.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.catalog import models as cm
from app.core import events
from app.crm import models as crm_m
from app.finance import models as fm
from app.identity import models as im
from app.orders import models as om
from app.settlements import models as m
from app.storefront import models as stm
from app.supply import models as sm

# Ledger parties that represent money the network owes outwards (§27).
SETTLEABLE_PARTIES = ["supplier", "logistics", "payment_processor", "luxeen", "operator", "customer"]

_GENERIC_COUNTERPARTY = {
    "luxeen": "Luxeen Network (platform economics)",
    "logistics": "Corridor logistics partners",
    "payment_processor": "Payment processor",
}


def _supplier_for_order(db: Session, order_id: int) -> str:
    item = db.query(om.OrderItem).filter(om.OrderItem.order_id == order_id).first()
    if item:
        product = db.get(cm.Product, item.product_id)
        if product:
            supplier = db.get(sm.Supplier, product.supplier_id)
            if supplier:
                return f"{supplier.name} ({supplier.city}, CN)"
    return "Unresolved supplier"


def _operator_for_order(db: Session, order_id: int) -> str:
    order = db.get(om.Order, order_id)
    if order:
        store = db.get(stm.Store, order.store_id)
        if store:
            org = db.get(im.Organization, store.org_id)
            if org:
                return f"{org.name} (operator)"
    return "Unresolved operator"


def _customer_for_order(db: Session, order_id: int) -> str:
    order = db.get(om.Order, order_id)
    if order:
        customer = db.get(crm_m.Customer, order.customer_id)
        if customer:
            return f"{customer.full_name} (refund)"
    return "Customer refunds"


def resolve_counterparty(db: Session, entry: fm.LedgerEntry) -> str:
    if entry.party in _GENERIC_COUNTERPARTY:
        return _GENERIC_COUNTERPARTY[entry.party]
    if entry.party == "supplier":
        return _supplier_for_order(db, entry.order_id) if entry.order_id else "Unresolved supplier"
    if entry.party == "operator":
        return _operator_for_order(db, entry.order_id) if entry.order_id else "Unresolved operator"
    if entry.party == "customer":
        return _customer_for_order(db, entry.order_id) if entry.order_id else "Customer refunds"
    return entry.party


def unsettled_summary(db: Session, *, order_ids: list[int] | None = None) -> dict:
    """What a new run WOULD settle, grouped like the resulting lines."""
    q = (
        db.query(fm.LedgerEntry)
        .filter(
            fm.LedgerEntry.amount < 0,
            fm.LedgerEntry.party.in_(SETTLEABLE_PARTIES),
            fm.LedgerEntry.settlement_run_id.is_(None),
        )
    )
    if order_ids:
        q = q.filter(fm.LedgerEntry.order_id.in_(order_ids))
    entries = q.order_by(fm.LedgerEntry.id.asc()).all()

    buckets: dict[tuple, dict] = {}
    for e in entries:
        key = (e.entry_type, e.party, resolve_counterparty(db, e), e.currency)
        b = buckets.setdefault(
            key, {"entry_type": e.entry_type, "party": e.party, "counterparty": key[2],
                  "currency": e.currency, "amount": 0.0, "entry_count": 0, "entry_ids": []}
        )
        b["amount"] = round(b["amount"] + e.amount, 2)
        b["entry_count"] += 1
        b["entry_ids"].append(e.id)

    lines = sorted(buckets.values(), key=lambda b: (b["party"], b["counterparty"]))
    return {
        "lines": lines,
        "total_amount": round(sum(l["amount"] for l in lines), 2),
        "entry_count": len(entries),
        "currencies": sorted({l["currency"] for l in lines}),
    }


def build_run(
    db: Session,
    *,
    note: str = "",
    order_ids: list[int] | None = None,
    org_id: int | None = None,
) -> m.SettlementRun:
    """Create a draft run from currently unsettled payables."""
    summary = unsettled_summary(db, order_ids=order_ids)
    if not summary["lines"]:
        raise ValueError("Nothing to settle — no unsettled payable ledger entries")

    run = m.SettlementRun(
        run_number="pending", org_id=org_id, status="draft",
        currency=summary["currencies"][0] if len(summary["currencies"]) == 1 else "MIXED",
        total_amount=summary["total_amount"], entry_count=summary["entry_count"],
        line_count=len(summary["lines"]), note=note,
    )
    db.add(run)
    db.flush()
    run.run_number = f"STL-{run.id:05d}"

    for b in summary["lines"]:
        db.add(m.SettlementLine(
            run_id=run.id, entry_type=b["entry_type"], party=b["party"],
            counterparty=b["counterparty"], currency=b["currency"],
            amount=b["amount"], entry_count=b["entry_count"], entry_ids=b["entry_ids"],
        ))

    db.flush()
    events.publish(db, "settlement.created", {
        "run_id": run.id, "run_number": run.run_number,
        "total_amount": run.total_amount, "line_count": run.line_count,
        "entry_count": run.entry_count, "currency": run.currency,
    })
    return run


def _transition(db: Session, run: m.SettlementRun, new_status: str) -> None:
    allowed = m.SETTLEMENT_TRANSITIONS.get(run.status, [])
    if new_status not in allowed:
        raise ValueError(f"Illegal settlement transition {run.status} -> {new_status}")
    old = run.status
    run.status = new_status
    events.publish(db, "settlement.status_changed", {
        "run_id": run.id, "run_number": run.run_number, "from": old, "to": new_status,
    })


def approve_run(db: Session, run: m.SettlementRun) -> m.SettlementRun:
    _transition(db, run, "approved")
    return run


def cancel_run(db: Session, run: m.SettlementRun) -> m.SettlementRun:
    _transition(db, run, "cancelled")
    return run


def execute_run(db: Session, run: m.SettlementRun) -> m.SettlementRun:
    """Approve-then-execute: stamp the ledger entries as settled and fire
    `settlement.completed` (§27) so payouts/notifications can react."""
    _transition(db, run, "executed")
    now = datetime.now(timezone.utc)

    lines = db.query(m.SettlementLine).filter(m.SettlementLine.run_id == run.id).all()
    settled_orders: set[int] = set()
    for line in lines:
        entries = (
            db.query(fm.LedgerEntry)
            .filter(fm.LedgerEntry.id.in_(line.entry_ids))
            .all()
        )
        for e in entries:
            e.settlement_run_id = run.id
            e.settled_at = now
            if e.order_id:
                settled_orders.add(e.order_id)

    run.executed_at = now
    events.publish(db, "settlement.completed", {
        "run_id": run.id, "run_number": run.run_number,
        "total_amount": run.total_amount, "currency": run.currency,
        "line_count": run.line_count, "entry_count": run.entry_count,
        "order_ids": sorted(settled_orders),
    })
    return run


def serialize_run(db: Session, run: m.SettlementRun, *, with_lines: bool = False) -> dict:
    data = {
        "id": run.id, "run_number": run.run_number, "org_id": run.org_id,
        "status": run.status, "currency": run.currency,
        "total_amount": run.total_amount, "entry_count": run.entry_count,
        "line_count": run.line_count, "note": run.note,
        "executed_at": run.executed_at.isoformat() if run.executed_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }
    if with_lines:
        lines = (
            db.query(m.SettlementLine)
            .filter(m.SettlementLine.run_id == run.id)
            .order_by(m.SettlementLine.id.asc())
            .all()
        )
        data["lines"] = [
            {
                "id": l.id, "entry_type": l.entry_type, "party": l.party,
                "counterparty": l.counterparty, "currency": l.currency,
                "amount": l.amount, "entry_count": l.entry_count,
                "entry_ids": l.entry_ids,
            }
            for l in lines
        ]
    return data
