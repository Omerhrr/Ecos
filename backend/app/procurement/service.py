"""Procurement service (plan §21-22) — POs + Stock Prophet reorder actions.

Loop this module closes:

    Stock Prophet run (§33, advisory)
        -> ai.run.completed subscriber materialises ReorderSuggestions
        -> procurement reviews them (open / dismiss)
        -> po_from_suggestions() groups by supplier and raises POs
        -> submit -> confirm -> receive  (units back into product stock)
        -> notifications fan the whole story out to the team (§39)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.ai_harness import models as aim
from app.catalog import models as cm
from app.core import events
from app.procurement import models as m
from app.supply import models as sm


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _next_po_number(db: Session) -> str:
    last = db.query(m.PurchaseOrder).order_by(m.PurchaseOrder.id.desc()).first()
    return f"PO-{(last.id if last else 0) + 1:05d}"


# --------------------------------------------------------------------------
# Stock Prophet suggestions (§33 -> procurement bridge)
# --------------------------------------------------------------------------

def sync_suggestions_from_run(db: Session, run: aim.AiRun) -> dict[str, Any]:
    """Materialise a demand-forecaster run's output as ReorderSuggestions.

    Idempotent per (run_id, product_id). Suggestions still open from older
    runs are marked `superseded` — the newest run is the single source of
    truth for what procurement should act on.
    """
    rows = (run.output or {}).get("products") or []
    fresh = 0
    for row in rows:
        try:
            product_id = int(row.get("product_id") or 0)
            qty = int(row.get("suggested_reorder_qty") or 0)
        except (TypeError, ValueError):
            continue
        if not product_id or qty <= 0:
            continue
        cover = row.get("weeks_of_cover")
        existing = (
            db.query(m.ReorderSuggestion)
            .filter(
                m.ReorderSuggestion.run_id == run.id,
                m.ReorderSuggestion.product_id == product_id,
            )
            .first()
        )
        if existing:
            existing.risk = row.get("risk", existing.risk)
            existing.weekly_velocity = float(row.get("weekly_velocity") or 0.0)
            existing.weeks_of_cover = float(cover) if cover is not None else None
            existing.stock_at_time = int(row.get("stock") or 0)
            existing.suggested_qty = qty
            continue
        db.add(m.ReorderSuggestion(
            product_id=product_id, run_id=run.id, org_id=run.org_id,
            risk=row.get("risk", "watch"),
            weekly_velocity=float(row.get("weekly_velocity") or 0.0),
            weeks_of_cover=float(cover) if cover is not None else None,
            stock_at_time=int(row.get("stock") or 0),
            suggested_qty=qty,
        ))
        fresh += 1

    db.flush()

    # older open suggestions are stale — the latest run is the truth
    db.query(m.ReorderSuggestion).filter(
        m.ReorderSuggestion.status == "open",
        m.ReorderSuggestion.run_id != run.id,
    ).update({"status": "superseded"}, synchronize_session=False)
    db.flush()

    open_count = (
        db.query(m.ReorderSuggestion)
        .filter(m.ReorderSuggestion.status == "open")
        .count()
    )
    if fresh or open_count:
        events.publish(db, "reorder.suggested", {
            "run_id": run.id, "org_id": run.org_id,
            "fresh_count": fresh, "open_count": open_count,
        })
    return {"run_id": run.id, "fresh": fresh, "open": open_count}


def refresh_from_latest_run(db: Session) -> dict[str, Any]:
    """Backfill suggestions from the newest successful Stock Prophet run."""
    run = (
        db.query(aim.AiRun, aim.AiOperator)
        .join(aim.AiOperator, aim.AiOperator.id == aim.AiRun.operator_id)
        .filter(
            aim.AiOperator.code == "demand_forecaster",
            aim.AiRun.status == "succeeded",
        )
        .order_by(aim.AiRun.id.desc())
        .first()
    )
    if not run:
        raise ValueError("No successful Stock Prophet run yet — run the demand_forecaster operator first")
    ai_run = run[0]
    summary = sync_suggestions_from_run(db, ai_run)
    summary["open_suggestions"] = summary.pop("open")
    summary["new_suggestions"] = summary.pop("fresh")
    return summary


# --------------------------------------------------------------------------
# Purchase orders
# --------------------------------------------------------------------------

def create_po(
    db: Session,
    *,
    supplier_id: int,
    lines: list[dict[str, int]],
    org_id: int | None = None,
    created_by: int | None = None,
    expected_at: datetime | None = None,
    note: str = "",
    source: str = "manual",
    source_run_id: int | None = None,
) -> m.PurchaseOrder:
    supplier = db.get(sm.Supplier, supplier_id)
    if supplier is None:
        raise ValueError("Supplier not found")
    clean_lines: list[tuple[cm.Product, int]] = []
    for line in lines:
        try:
            product_id = int(line.get("product_id") or 0)
            qty = int(line.get("qty") or 0)
        except (AttributeError, TypeError, ValueError):
            raise ValueError("Each line needs product_id and qty")
        if qty < 1:
            raise ValueError("Line qty must be >= 1")
        product = db.get(cm.Product, product_id)
        if product is None:
            raise ValueError(f"Product {product_id} not found")
        if product.supplier_id != supplier_id:
            raise ValueError(
                f"Product {product_id} ({product.title}) belongs to another supplier — "
                "group POs per supplier"
            )
        clean_lines.append((product, qty))
    if not clean_lines:
        raise ValueError("A PO needs at least one line")

    po = m.PurchaseOrder(
        po_number=_next_po_number(db), supplier_id=supplier_id,
        currency=clean_lines[0][0].currency or "CNY",
        expected_at=expected_at, note=note[:1024],
        source=source, source_run_id=source_run_id,
        org_id=org_id, created_by=created_by,
    )
    db.add(po)
    db.flush()

    total = 0.0
    for product, qty in clean_lines:
        db.add(m.PurchaseOrderLine(
            po_id=po.id, product_id=product.id,
            qty_ordered=qty, unit_cost=float(product.supplier_cost or 0.0),
        ))
        total += float(product.supplier_cost or 0.0) * qty
    po.items_total = round(total, 2)
    db.flush()

    events.publish(db, "procurement.po_created", {
        "po_id": po.id, "po_number": po.po_number,
        "supplier_id": supplier_id, "supplier_name": supplier.name,
        "org_id": org_id, "line_count": len(clean_lines),
        "units": sum(q for _, q in clean_lines),
        "items_total": po.items_total, "currency": po.currency,
        "source": source,
    })
    return po


def po_from_suggestions(
    db: Session,
    *,
    suggestion_ids: list[int] | None = None,
    org_id: int | None = None,
    created_by: int | None = None,
    expected_at: datetime | None = None,
    note: str = "",
) -> list[m.PurchaseOrder]:
    """Convert open reorder suggestions into POs — one per supplier.

    Empty `suggestion_ids` converts ALL open suggestions.
    """
    q = db.query(m.ReorderSuggestion).filter(m.ReorderSuggestion.status == "open")
    if suggestion_ids:
        q = q.filter(m.ReorderSuggestion.id.in_(suggestion_ids))
    suggestions = q.order_by(m.ReorderSuggestion.id).all()
    if not suggestions:
        raise ValueError("No open reorder suggestions to convert")

    by_supplier: dict[int, list[m.ReorderSuggestion]] = {}
    for s in suggestions:
        product = db.get(cm.Product, s.product_id)
        if product is None:
            s.status = "dismissed"
            s.resolved_at = _now()
            continue
        by_supplier.setdefault(product.supplier_id, []).append(s)

    if not by_supplier:
        raise ValueError("No actionable suggestions — products missing")

    pos: list[m.PurchaseOrder] = []
    for supplier_id, group in by_supplier.items():
        run_id = group[0].run_id
        po = create_po(
            db, supplier_id=supplier_id,
            lines=[{"product_id": s.product_id, "qty": s.suggested_qty} for s in group],
            org_id=org_id, created_by=created_by, expected_at=expected_at,
            note=note or "Raised from Stock Prophet reorder suggestions",
            source="stock_prophet", source_run_id=run_id,
        )
        now = _now()
        for s in group:
            s.status = "converted"
            s.po_id = po.id
            s.resolved_at = now
        db.flush()
        pos.append(po)
    return pos


def _transition(db: Session, po: m.PurchaseOrder, new_status: str) -> None:
    allowed = m.PO_TRANSITIONS.get(po.status, [])
    if new_status not in allowed:
        raise ValueError(f"Illegal PO transition {po.status} -> {new_status}")
    old = po.status
    po.status = new_status
    stamp = {
        "submitted": "submitted_at", "confirmed": "confirmed_at",
        "received": "received_at", "cancelled": "cancelled_at",
    }.get(new_status)
    if stamp:
        setattr(po, stamp, _now())
    events.publish(db, "procurement.po_status_changed", {
        "po_id": po.id, "po_number": po.po_number, "from": old, "to": new_status,
        "org_id": po.org_id,
    })


def submit_po(db: Session, po: m.PurchaseOrder) -> m.PurchaseOrder:
    _transition(db, po, "submitted")
    return po


def confirm_po(db: Session, po: m.PurchaseOrder) -> m.PurchaseOrder:
    _transition(db, po, "confirmed")
    return po


def cancel_po(db: Session, po: m.PurchaseOrder) -> m.PurchaseOrder:
    _transition(db, po, "cancelled")
    reopened = (
        db.query(m.ReorderSuggestion)
        .filter(m.ReorderSuggestion.po_id == po.id, m.ReorderSuggestion.status == "converted")
        .all()
    )
    for s in reopened:
        s.status = "open"
        s.po_id = None
        s.resolved_at = None
    db.flush()
    events.publish(db, "procurement.po_cancelled", {
        "po_id": po.id, "po_number": po.po_number, "org_id": po.org_id,
        "reopened_suggestions": len(reopened),
    })
    return po


def receive_po(
    db: Session, po: m.PurchaseOrder, receipts: dict[int, int]
) -> m.PurchaseOrder:
    """Post a goods receipt: {line_id: qty}. Full coverage flips the PO to received."""
    if po.status not in m.RECEIVABLE_STATUSES:
        raise ValueError(f"Goods receipt requires a confirmed PO (this one is {po.status})")
    if not receipts:
        raise ValueError("Nothing to receive")

    lines = {
        l.id: l
        for l in db.query(m.PurchaseOrderLine).filter(m.PurchaseOrderLine.po_id == po.id).all()
    }
    received_now = 0
    for line_id, qty in receipts.items():
        line = lines.get(int(line_id))
        if line is None:
            raise ValueError(f"Line {line_id} is not on PO {po.po_number}")
        if qty <= 0:
            raise ValueError("Receive qty must be >= 1")
        if line.qty_received + qty > line.qty_ordered:
            raise ValueError(
                f"Cannot receive {qty}: line {line_id} has "
                f"{line.qty_ordered - line.qty_received} of {line.qty_ordered} outstanding"
            )
        line.qty_received += qty
        received_now += qty
        product = db.get(cm.Product, line.product_id)
        if product is not None:
            product.stock += qty

    db.flush()

    outstanding = (
        db.query(m.PurchaseOrderLine)
        .filter(
            m.PurchaseOrderLine.po_id == po.id,
            m.PurchaseOrderLine.qty_received < m.PurchaseOrderLine.qty_ordered,
        )
        .count()
    )
    if outstanding == 0:
        _transition(db, po, "received")
        events.publish(db, "procurement.po_received", {
            "po_id": po.id, "po_number": po.po_number, "org_id": po.org_id,
            "units": received_now,
        })
    else:
        events.publish(db, "procurement.po_receiving", {
            "po_id": po.id, "po_number": po.po_number, "org_id": po.org_id,
            "units": received_now, "outstanding_lines": outstanding,
        })
    return po


# --------------------------------------------------------------------------
# Serializers
# --------------------------------------------------------------------------

def serialize_line(db: Session, line: m.PurchaseOrderLine) -> dict[str, Any]:
    product = db.get(cm.Product, line.product_id)
    return {
        "id": line.id, "product_id": line.product_id,
        "product_title": product.title if product else None,
        "qty_ordered": line.qty_ordered, "qty_received": line.qty_received,
        "qty_outstanding": line.qty_ordered - line.qty_received,
        "unit_cost": line.unit_cost,
        "line_total": round(line.unit_cost * line.qty_ordered, 2),
    }


def serialize_po(db: Session, po: m.PurchaseOrder, *, with_lines: bool = False) -> dict[str, Any]:
    supplier = db.get(sm.Supplier, po.supplier_id)
    data = {
        "id": po.id, "po_number": po.po_number,
        "supplier_id": po.supplier_id,
        "supplier_name": supplier.name if supplier else None,
        "supplier_lead_time_days": supplier.lead_time_days if supplier else None,
        "status": po.status, "currency": po.currency,
        "items_total": po.items_total, "freight": po.freight,
        "expected_at": po.expected_at.isoformat() if po.expected_at else None,
        "note": po.note, "source": po.source, "source_run_id": po.source_run_id,
        "org_id": po.org_id, "created_by": po.created_by,
        "submitted_at": po.submitted_at.isoformat() if po.submitted_at else None,
        "confirmed_at": po.confirmed_at.isoformat() if po.confirmed_at else None,
        "received_at": po.received_at.isoformat() if po.received_at else None,
        "cancelled_at": po.cancelled_at.isoformat() if po.cancelled_at else None,
        "created_at": po.created_at.isoformat() if po.created_at else None,
        "allowed_transitions": m.PO_TRANSITIONS.get(po.status, []),
    }
    if with_lines:
        lines = (
            db.query(m.PurchaseOrderLine)
            .filter(m.PurchaseOrderLine.po_id == po.id)
            .order_by(m.PurchaseOrderLine.id)
            .all()
        )
        data["lines"] = [serialize_line(db, l) for l in lines]
    return data


def serialize_suggestion(db: Session, s: m.ReorderSuggestion) -> dict[str, Any]:
    product = db.get(cm.Product, s.product_id)
    supplier_id = product.supplier_id if product else None
    supplier = db.get(sm.Supplier, supplier_id) if supplier_id else None
    return {
        "id": s.id, "product_id": s.product_id,
        "product_title": product.title if product else None,
        "product_stock": product.stock if product else None,
        "supplier_id": supplier_id,
        "supplier_name": supplier.name if supplier else None,
        "supplier_lead_time_days": supplier.lead_time_days if supplier else None,
        "run_id": s.run_id, "org_id": s.org_id, "status": s.status,
        "risk": s.risk, "weekly_velocity": s.weekly_velocity,
        "weeks_of_cover": s.weeks_of_cover, "stock_at_time": s.stock_at_time,
        "suggested_qty": s.suggested_qty, "po_id": s.po_id,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "resolved_at": s.resolved_at.isoformat() if s.resolved_at else None,
    }
