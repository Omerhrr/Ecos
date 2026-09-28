"""Warehouse domain events -> notification fan-out (§22 x §39).

Only operationally interesting moments notify: a wave is created (work to
do), completed (orders are on their way), stock is adjusted down (possible
shrinkage), and transfers (stock moved between locations).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core import events
from app.notifications import service as svc


def _on_wave_created(db: Session, p: dict) -> None:
    svc.notify(
        db, org_id=p.get("org_id"), category="shipments", level="info",
        title=f"Pick wave {p.get('wave_number')} created — {p.get('order_count')} order(s)",
        body=f"Wave is ready to pick at warehouse {p.get('warehouse_code') or p.get('warehouse_id')}.",
        entity_type="pick_wave", entity_id=p.get("wave_id"),
    )


def _on_wave_completed(db: Session, p: dict) -> None:
    orders = p.get("order_ids") or []
    svc.notify(
        db, org_id=p.get("org_id"), category="shipments", level="success",
        title=f"Pick wave {p.get('wave_number')} completed",
        body=f"{len(orders)} order(s) handed to logistics — shipments "
             f"{', '.join('#' + str(s) for s in (p.get('shipment_ids') or [])) or 'n/a'}.",
        entity_type="pick_wave", entity_id=p.get("wave_id"),
    )


def _on_stock_adjusted(db: Session, p: dict) -> None:
    delta = int(p.get("delta") or 0)
    if delta >= 0:
        return  # positive corrections are housekeeping; only losses alert
    svc.notify(
        db, org_id=None, category="shipments", level="warning",
        title=f"Stock adjusted {delta} on product #{p.get('product_id')}",
        body=f"Cycle-count correction: {p.get('reason') or 'no reason given'}. "
             f"On-hand is now {p.get('on_hand')}.",
        entity_type="product", entity_id=p.get("product_id"),
    )


def _on_stock_transferred(db: Session, p: dict) -> None:
    svc.notify(
        db, org_id=None, category="shipments", level="info",
        title=f"{p.get('qty')} unit(s) transferred between warehouses",
        body=f"Product #{p.get('product_id')} moved — both legs are on the stock ledger.",
        entity_type="product", entity_id=p.get("product_id"),
    )


def register() -> None:
    events.subscribe("warehouse.wave_created", _on_wave_created)
    events.subscribe("warehouse.wave_completed", _on_wave_completed)
    events.subscribe("warehouse.stock_adjusted", _on_stock_adjusted)
    events.subscribe("warehouse.stock_transferred", _on_stock_transferred)
