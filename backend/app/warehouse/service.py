"""Warehouse / fulfillment service (plan §22 deep-dive).

Responsibilities:
1. Putaway — procurement goods receipts land as StockMovements (`receipt`)
   against a warehouse, updating per-warehouse StockItems (§22 x §21).
2. Cycle control — manual adjustments and inter-warehouse transfers, every
   unit accounted for in the immutable movement ledger.
3. Pick waves — batch customer orders, pick (stock leaves the warehouse),
   pack, then hand off to logistics: shipments are created and orders
   advance to `fulfilled` (§22 x §19-20).

Network-level `product.stock` stays the storefront oversell guard; the
warehouse layer explains WHERE the units physically are.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.catalog import models as cm
from app.core import events
from app.warehouse import models as m

# imported here (not lazily) — orders metadata is always loaded before warehouse use
from app.orders import models as om

FULFILLABLE_ORDER_STATUSES = ["confirmed", "processing"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _next_warehouse_code(db: Session) -> str:
    last = db.query(m.Warehouse).order_by(m.Warehouse.id.desc()).first()
    return f"WH-{(last.id if last else 0) + 1:03d}"


def _next_wave_number(db: Session) -> str:
    last = db.query(m.PickWave).order_by(m.PickWave.id.desc()).first()
    return f"WV-{(last.id if last else 0) + 1:05d}"


# --------------------------------------------------------------------------
# Warehouses
# --------------------------------------------------------------------------

def create_warehouse(
    db: Session, *, name: str, org_id: int | None = None, city: str = "",
    country: str = "NG", address: str = "", is_default: bool = False,
) -> m.Warehouse:
    if not name or not name.strip():
        raise ValueError("Warehouse name is required")
    if is_default:
        # only one default at a time
        db.query(m.Warehouse).filter(m.Warehouse.is_default.is_(True)).update(
            {"is_default": False}, synchronize_session=False
        )
    wh = m.Warehouse(
        code=_next_warehouse_code(db), name=name.strip()[:255],
        org_id=org_id, city=city[:100], country=country[:2].upper() or "NG",
        address=address[:1024], is_default=is_default,
    )
    db.add(wh)
    db.flush()
    return wh


def ensure_default_warehouse(db: Session, org_id: int | None) -> m.Warehouse:
    """Get-or-create the org's default receiving warehouse (idempotent)."""
    q = db.query(m.Warehouse).filter(m.Warehouse.status == "active")
    wh = None
    if org_id is not None:
        wh = q.filter(m.Warehouse.org_id == org_id, m.Warehouse.is_default.is_(True)).first()
        if wh is None:
            wh = q.filter(m.Warehouse.org_id == org_id).first()
    if wh is None:
        wh = q.filter(m.Warehouse.is_default.is_(True)).first()
    if wh is None:
        wh = q.order_by(m.Warehouse.id).first()
    if wh is None:
        wh = create_warehouse(
            db, name="Main Warehouse", org_id=org_id, city="Lagos",
            country="NG", is_default=True,
        )
    return wh


# --------------------------------------------------------------------------
# Stock primitives (every change flows through here)
# --------------------------------------------------------------------------

def _get_stock_item(db: Session, warehouse_id: int, product_id: int, *, create: bool = True) -> m.StockItem | None:
    row = (
        db.query(m.StockItem)
        .filter(m.StockItem.warehouse_id == warehouse_id, m.StockItem.product_id == product_id)
        .first()
    )
    if row is None and create:
        row = m.StockItem(warehouse_id=warehouse_id, product_id=product_id, on_hand=0)
        db.add(row)
        db.flush()
    return row


def _post_movement(
    db: Session, *, warehouse_id: int, product_id: int, movement_type: str,
    qty: int, reference_type: str, reference_id: int | None, note: str,
    created_by: int | None, balance_after: int,
) -> m.StockMovement:
    row = m.StockMovement(
        warehouse_id=warehouse_id, product_id=product_id, movement_type=movement_type,
        qty=qty, balance_after=balance_after, reference_type=reference_type,
        reference_id=reference_id, note=note[:1024], created_by=created_by,
    )
    db.add(row)
    db.flush()
    return row


def receive_stock(
    db: Session, *, warehouse: m.Warehouse, product: cm.Product, qty: int,
    reference_type: str = "purchase_order", reference_id: int | None = None,
    note: str = "", created_by: int | None = None,
) -> m.StockMovement:
    """Putaway: positive units into a warehouse (PO goods receipt)."""
    if qty <= 0:
        raise ValueError("Received qty must be >= 1")
    item = _get_stock_item(db, warehouse.id, product.id)
    item.on_hand += qty
    db.flush()
    return _post_movement(
        db, warehouse_id=warehouse.id, product_id=product.id, movement_type="receipt",
        qty=qty, reference_type=reference_type, reference_id=reference_id,
        note=note, created_by=created_by, balance_after=item.on_hand,
    )


def adjust_stock(
    db: Session, *, warehouse_id: int, product: cm.Product, delta: int,
    reason: str, created_by: int | None = None,
) -> m.StockMovement:
    """Cycle-count correction: signed delta on both warehouse + network stock."""
    if delta == 0:
        raise ValueError("Adjustment delta must be non-zero")
    item = _get_stock_item(db, warehouse_id, product.id)
    if item.on_hand + delta < 0:
        raise ValueError(
            f"Adjustment would go negative: on-hand {item.on_hand}, delta {delta}"
        )
    item.on_hand += delta
    product.stock = max(0, (product.stock or 0) + delta)
    db.flush()
    events.publish(db, "warehouse.stock_adjusted", {
        "warehouse_id": warehouse_id, "product_id": product.id,
        "delta": delta, "on_hand": item.on_hand, "reason": reason[:300],
    })
    return _post_movement(
        db, warehouse_id=warehouse_id, product_id=product.id, movement_type="adjustment",
        qty=delta, reference_type="adjustment", reference_id=None,
        note=reason, created_by=created_by, balance_after=item.on_hand,
    )


def transfer_stock(
    db: Session, *, from_warehouse_id: int, to_warehouse_id: int,
    product: cm.Product, qty: int, created_by: int | None = None,
) -> list[m.StockMovement]:
    """Move units between two warehouses (two ledger rows, one product)."""
    if qty <= 0:
        raise ValueError("Transfer qty must be >= 1")
    if from_warehouse_id == to_warehouse_id:
        raise ValueError("Source and destination warehouses must differ")
    src = db.get(m.Warehouse, from_warehouse_id)
    dst = db.get(m.Warehouse, to_warehouse_id)
    if src is None or dst is None:
        raise ValueError("Source and destination warehouses must exist")
    src_item = _get_stock_item(db, from_warehouse_id, product.id)
    if src_item.on_hand < qty:
        raise ValueError(
            f"Insufficient stock at {src.name}: on-hand {src_item.on_hand}, transfer {qty}"
        )
    dst_item = _get_stock_item(db, to_warehouse_id, product.id)
    src_item.on_hand -= qty
    dst_item.on_hand += qty
    db.flush()
    out = _post_movement(
        db, warehouse_id=from_warehouse_id, product_id=product.id, movement_type="transfer_out",
        qty=-qty, reference_type="transfer", reference_id=to_warehouse_id,
        note=f"Transfer to {dst.code} {dst.name}", created_by=created_by,
        balance_after=src_item.on_hand,
    )
    inn = _post_movement(
        db, warehouse_id=to_warehouse_id, product_id=product.id, movement_type="transfer_in",
        qty=qty, reference_type="transfer", reference_id=from_warehouse_id,
        note=f"Transfer from {src.code} {src.name}", created_by=created_by,
        balance_after=dst_item.on_hand,
    )
    events.publish(db, "warehouse.stock_transferred", {
        "product_id": product.id, "qty": qty,
        "from_warehouse_id": from_warehouse_id, "to_warehouse_id": to_warehouse_id,
    })
    return [out, inn]


# --------------------------------------------------------------------------
# Pick waves (§22 fulfillment)
# --------------------------------------------------------------------------

def create_wave(
    db: Session, *, warehouse_id: int | None, order_ids: list[int],
    created_by: int | None = None, org_id: int | None = None, note: str = "",
) -> m.PickWave:
    from app.orders import models as om
    from app.logistics import models as lm

    if not order_ids:
        raise ValueError("A pick wave needs at least one order")
    wh = db.get(m.Warehouse, warehouse_id) if warehouse_id else None
    if wh is None:
        wh = ensure_default_warehouse(db, org_id)

    orders = (
        db.query(om.Order).filter(om.Order.id.in_(order_ids)).order_by(om.Order.id).all()
    )
    if len(orders) != len(set(order_ids)):
        raise ValueError("One or more orders not found")
    for order in orders:
        if order.status not in FULFILLABLE_ORDER_STATUSES:
            raise ValueError(
                f"Order {order.id} is {order.status} — only confirmed/processing orders can be waved"
            )
        existing_shipment = (
            db.query(lm.Shipment).filter(lm.Shipment.order_id == order.id).first()
        )
        if existing_shipment is not None:
            raise ValueError(f"Order {order.id} already has a shipment — nothing to wave")

    wave = m.PickWave(
        wave_number=_next_wave_number(db), warehouse_id=wh.id, org_id=org_id,
        status="open", order_count=len(orders), note=note[:1024], created_by=created_by,
    )
    db.add(wave)
    db.flush()

    for order in orders:
        items = db.query(om.OrderItem).filter(om.OrderItem.order_id == order.id).all()
        if not items:
            raise ValueError(f"Order {order.id} has no lines")
        for it in items:
            db.add(m.PickLine(
                wave_id=wave.id, order_id=order.id, product_id=it.product_id,
                title=it.title, qty=it.qty,
            ))
    db.flush()

    # availability check — the wave is created anyway only if everything is on the shelf
    shortages = _wave_shortages(db, wave)
    events.publish(db, "warehouse.wave_created", {
        "wave_id": wave.id, "wave_number": wave.wave_number,
        "warehouse_id": wh.id, "warehouse_code": wh.code,
        "order_count": wave.order_count, "org_id": org_id,
        "stock_shortages": shortages,
    })
    return wave


def _wave_shortages(db: Session, wave: m.PickWave) -> list[dict[str, Any]]:
    """Products whose on-hand at this warehouse can't cover the wave."""
    lines = db.query(m.PickLine).filter(m.PickLine.wave_id == wave.id).all()
    need: dict[int, int] = {}
    for l in lines:
        need[l.product_id] = need.get(l.product_id, 0) + l.qty
    shortages = []
    for product_id, qty in need.items():
        item = _get_stock_item(db, wave.warehouse_id, product_id, create=False)
        on_hand = item.on_hand if item else 0
        if on_hand < qty:
            shortages.append({"product_id": product_id, "on_hand": on_hand, "needed": qty})
    return shortages


def _wave_or_guard(wave: m.PickWave, action: str) -> None:
    allowed = m.WAVE_TRANSITIONS.get(wave.status, [])
    target = {"pick": "picking", "pack": "packed", "complete": "completed", "cancel": "cancelled"}[action]
    if target not in allowed:
        raise ValueError(f"Cannot {action} a wave that is {wave.status}")


def pick_wave(db: Session, wave: m.PickWave, *, actor: int | None = None) -> m.PickWave:
    """Take stock off the shelves for every line and move the wave to `picking`."""
    _wave_or_guard(wave, "pick")
    shortages = _wave_shortages(db, wave)
    if shortages:
        s = shortages[0]
        raise ValueError(
            f"Not enough stock at this warehouse for product {s['product_id']} "
            f"(on-hand {s['on_hand']}, needed {s['needed']}) — transfer stock in first"
        )
    lines = db.query(m.PickLine).filter(m.PickLine.wave_id == wave.id).all()
    for line in lines:
        item = _get_stock_item(db, wave.warehouse_id, line.product_id)
        item.on_hand -= line.qty
        line.picked_qty = line.qty
        line.status = "picked"
        db.flush()
        _post_movement(
            db, warehouse_id=wave.warehouse_id, product_id=line.product_id,
            movement_type="pick", qty=-line.qty, reference_type="order",
            reference_id=line.order_id, note=f"Pick wave {wave.wave_number}",
            created_by=actor, balance_after=item.on_hand,
        )
    wave.status = "picking"
    wave.picked_at = _now()
    events.publish(db, "warehouse.wave_picked", {
        "wave_id": wave.id, "wave_number": wave.wave_number,
        "warehouse_id": wave.warehouse_id, "org_id": wave.org_id,
        "line_count": len(lines),
    })
    return wave


def pack_wave(db: Session, wave: m.PickWave, *, actor: int | None = None) -> m.PickWave:
    _wave_or_guard(wave, "pack")
    lines = db.query(m.PickLine).filter(m.PickLine.wave_id == wave.id).all()
    for line in lines:
        if line.status != "picked":
            raise ValueError(f"Line {line.id} is not picked yet — pick the wave first")
        line.status = "packed"
    wave.status = "packed"
    wave.packed_at = _now()
    events.publish(db, "warehouse.wave_packed", {
        "wave_id": wave.id, "wave_number": wave.wave_number,
        "warehouse_id": wave.warehouse_id, "org_id": wave.org_id,
    })
    return wave


def complete_wave(db: Session, wave: m.PickWave, *, actor: int | None = None) -> m.PickWave:
    """Hand the wave to logistics: create shipments, orders go to `fulfilled`."""
    from app.logistics import models as lm
    from app.logistics import service as logistics_service

    _wave_or_guard(wave, "complete")
    order_ids = sorted({l.order_id for l in db.query(m.PickLine).filter(m.PickLine.wave_id == wave.id).all()})
    shipment_ids: list[int] = []
    for order_id in order_ids:
        order = db.get(om.Order, order_id)
        if order is None:
            continue
        existing = db.query(lm.Shipment).filter(lm.Shipment.order_id == order_id).first()
        if existing is not None:
            shipment_ids.append(existing.id)
            continue
        shipment = logistics_service.create_shipment_for_order(db, order)
        shipment_ids.append(shipment.id)
    wave.status = "completed"
    wave.completed_at = _now()
    events.publish(db, "warehouse.wave_completed", {
        "wave_id": wave.id, "wave_number": wave.wave_number,
        "warehouse_id": wave.warehouse_id, "org_id": wave.org_id,
        "order_ids": order_ids, "shipment_ids": shipment_ids,
    })
    return wave


def cancel_wave(db: Session, wave: m.PickWave, *, actor: int | None = None) -> m.PickWave:
    """Cancel side-exit: any picked stock goes back to the shelf."""
    _wave_or_guard(wave, "cancel")
    restocked = 0
    if wave.status in ("picking", "packed"):
        lines = db.query(m.PickLine).filter(m.PickLine.wave_id == wave.id).all()
        for line in lines:
            if line.picked_qty > 0:
                item = _get_stock_item(db, wave.warehouse_id, line.product_id)
                item.on_hand += line.picked_qty
                restocked += line.picked_qty
                _post_movement(
                    db, warehouse_id=wave.warehouse_id, product_id=line.product_id,
                    movement_type="return_restock", qty=line.picked_qty,
                    reference_type="wave", reference_id=wave.id,
                    note=f"Wave {wave.wave_number} cancelled — restock",
                    created_by=actor, balance_after=item.on_hand,
                )
    wave.status = "cancelled"
    wave.cancelled_at = _now()
    events.publish(db, "warehouse.wave_cancelled", {
        "wave_id": wave.id, "wave_number": wave.wave_number,
        "warehouse_id": wave.warehouse_id, "org_id": wave.org_id,
        "restocked_units": restocked,
    })
    return wave


# --------------------------------------------------------------------------
# Serializers
# --------------------------------------------------------------------------

def serialize_warehouse(db: Session, wh: m.Warehouse) -> dict[str, Any]:
    from sqlalchemy import func

    items = (
        db.query(m.StockItem)
        .filter(m.StockItem.warehouse_id == wh.id, m.StockItem.on_hand > 0)
        .count()
    )
    units = (
        db.query(func.coalesce(func.sum(m.StockItem.on_hand), 0))
        .filter(m.StockItem.warehouse_id == wh.id)
        .scalar()
    ) or 0
    open_waves = (
        db.query(m.PickWave)
        .filter(m.PickWave.warehouse_id == wh.id, m.PickWave.status.in_(["open", "picking", "packed"]))
        .count()
    )
    return {
        "id": wh.id, "code": wh.code, "name": wh.name, "city": wh.city,
        "country": wh.country, "address": wh.address, "status": wh.status,
        "is_default": bool(wh.is_default), "org_id": wh.org_id,
        "sku_count": items, "units_on_hand": units, "open_waves": open_waves,
        "created_at": wh.created_at.isoformat() if wh.created_at else None,
    }


def serialize_stock_row(db: Session, item: m.StockItem) -> dict[str, Any]:
    product = db.get(cm.Product, item.product_id)
    wh = db.get(m.Warehouse, item.warehouse_id)
    return {
        "id": item.id, "warehouse_id": item.warehouse_id,
        "warehouse_code": wh.code if wh else None,
        "warehouse_name": wh.name if wh else None,
        "product_id": item.product_id,
        "product_title": product.title if product else None,
        "product_stock": product.stock if product else None,
        "on_hand": item.on_hand, "reserved": item.reserved,
        "available": max(0, item.on_hand - item.reserved),
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def serialize_movement(db: Session, mv: m.StockMovement) -> dict[str, Any]:
    product = db.get(cm.Product, mv.product_id)
    wh = db.get(m.Warehouse, mv.warehouse_id)
    return {
        "id": mv.id, "warehouse_id": mv.warehouse_id,
        "warehouse_code": wh.code if wh else None,
        "product_id": mv.product_id,
        "product_title": product.title if product else None,
        "movement_type": mv.movement_type, "qty": mv.qty,
        "balance_after": mv.balance_after,
        "reference_type": mv.reference_type, "reference_id": mv.reference_id,
        "note": mv.note, "created_by": mv.created_by,
        "created_at": mv.created_at.isoformat() if mv.created_at else None,
    }


def serialize_line(line: m.PickLine) -> dict[str, Any]:
    return {
        "id": line.id, "order_id": line.order_id, "product_id": line.product_id,
        "title": line.title, "qty": line.qty, "picked_qty": line.picked_qty,
        "status": line.status,
    }


def serialize_wave(db: Session, wave: m.PickWave, *, with_lines: bool = False) -> dict[str, Any]:
    wh = db.get(m.Warehouse, wave.warehouse_id)
    data = {
        "id": wave.id, "wave_number": wave.wave_number,
        "warehouse_id": wave.warehouse_id,
        "warehouse_code": wh.code if wh else None,
        "warehouse_name": wh.name if wh else None,
        "org_id": wave.org_id, "status": wave.status,
        "order_count": wave.order_count, "note": wave.note,
        "created_by": wave.created_by,
        "picked_at": wave.picked_at.isoformat() if wave.picked_at else None,
        "packed_at": wave.packed_at.isoformat() if wave.packed_at else None,
        "completed_at": wave.completed_at.isoformat() if wave.completed_at else None,
        "cancelled_at": wave.cancelled_at.isoformat() if wave.cancelled_at else None,
        "created_at": wave.created_at.isoformat() if wave.created_at else None,
        "allowed_transitions": m.WAVE_TRANSITIONS.get(wave.status, []),
    }
    if with_lines:
        lines = (
            db.query(m.PickLine)
            .filter(m.PickLine.wave_id == wave.id)
            .order_by(m.PickLine.order_id, m.PickLine.id)
            .all()
        )
        data["lines"] = [serialize_line(l) for l in lines]
    return data
