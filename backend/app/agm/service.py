"""AGM service — the local fulfillment half of the corridor.

Owns:
  agent registration (self-service, plan: "people can register as agent")
  vendor <-> agent links
  inbound putaway of sourcing arrivals (per-vendor stock)
  the fulfillment alert lifecycle: notified -> accepted -> calling ->
  confirmed -> out_for_delivery -> delivered|failed (+ retry/return)
  COD custody: remittance registers with ledger-backed reconciliation (§24)

Customer-order state advances through the §19 machine as the agent works
(delivered auto-captures COD via the existing finance subscriber), so the
operator's dashboard and the AGM console always tell the same story.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.agm import models as m
from app.catalog import models as cm
from app.core import events
from app.crm import models as crm_m
from app.identity import models as im
from app.market import models as market_m
from app.orders import models as om
from app.orders import service as order_service


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _next_code(db: Session, model, prefix: str) -> str:
    last = db.query(model).order_by(model.id.desc()).first()
    return f"{prefix}-{(last.id if last else 0) + 1:05d}"


# ---------------------------------------------------------------------------
# Registration + links
# ---------------------------------------------------------------------------

def register_agent(
    db: Session, *, company: str, contact_name: str, email: str,
    password_hash: str, phone: str = "", whatsapp: str = "",
    city: str = "", country: str = "NG", address: str = "",
) -> dict[str, Any]:
    """Self-service agent signup: org (type=agent) + user (role=agm) + profile."""
    from app.identity import models as im

    email = email.strip().lower()
    if db.query(im.User).filter(im.User.email == email).first():
        raise ValueError("Email already registered")
    org = im.Organization(name=company.strip()[:255], type="agent", country=country[:2], currency="NGN")
    db.add(org)
    db.flush()
    user = im.User(
        org_id=org.id, name=contact_name.strip()[:255], email=email,
        phone=phone or None, role="agm", password_hash=password_hash,
    )
    db.add(user)
    profile = m.AgentProfile(
        org_id=org.id, contact_name=contact_name.strip()[:255],
        phone=phone, whatsapp=whatsapp or phone, city=city,
        country=country[:2], address=address,
    )
    db.add(profile)
    db.flush()
    events.publish(db, "agent.registered", {
        "org_id": org.id, "company": org.name, "city": city, "country": org.country,
    })
    return {"org_id": org.id, "user_id": user.id}


def add_link(db: Session, *, agent_org_id: int, vendor_org_id: int, created_by: int | None = None) -> m.AgentLink:
    profile = db.get(m.AgentProfile, agent_org_id)
    if profile is None or profile.status != "active":
        raise ValueError("Agent not found or suspended")
    existing = (
        db.query(m.AgentLink)
        .filter(m.AgentLink.agent_org_id == agent_org_id, m.AgentLink.vendor_org_id == vendor_org_id)
        .first()
    )
    if existing:
        existing.status = "active"
        db.flush()
        return existing
    link = m.AgentLink(agent_org_id=agent_org_id, vendor_org_id=vendor_org_id, created_by=created_by)
    db.add(link)
    db.flush()
    events.publish(db, "agent.linked", {
        "agent_org_id": agent_org_id, "vendor_org_id": vendor_org_id,
    })
    return link


# ---------------------------------------------------------------------------
# Warehouses + per-vendor inventory
# ---------------------------------------------------------------------------

def create_warehouse(
    db: Session, *, agent_org_id: int, name: str, city: str = "",
    country: str = "NG", address: str = "", is_default: bool = False,
) -> m.AgentWarehouse:
    count = db.query(m.AgentWarehouse).filter(m.AgentWarehouse.agent_org_id == agent_org_id).count()
    wh = m.AgentWarehouse(
        agent_org_id=agent_org_id,
        code=f"AGW-{agent_org_id}-{count + 1:02d}",
        name=name.strip()[:255], city=city, country=country[:2],
        address=address[:1024], is_default=1 if (is_default or count == 0) else 0,
    )
    db.add(wh)
    db.flush()
    if wh.is_default:
        db.query(m.AgentWarehouse).filter(
            m.AgentWarehouse.agent_org_id == agent_org_id,
            m.AgentWarehouse.id != wh.id,
        ).update({"is_default": 0}, synchronize_session=False)
    events.publish(db, "agent.warehouse_created", {
        "agent_org_id": agent_org_id, "warehouse_id": wh.id, "name": wh.name,
    })
    return wh


def ensure_default_agent_warehouse(db: Session, agent_org_id: int) -> m.AgentWarehouse:
    wh = (
        db.query(m.AgentWarehouse)
        .filter(m.AgentWarehouse.agent_org_id == agent_org_id, m.AgentWarehouse.is_default == 1)
        .first()
    ) or (
        db.query(m.AgentWarehouse)
        .filter(m.AgentWarehouse.agent_org_id == agent_org_id, m.AgentWarehouse.status == "active")
        .order_by(m.AgentWarehouse.id)
        .first()
    )
    if wh is None:
        wh = create_warehouse(db, agent_org_id=agent_org_id, name="Main Warehouse", is_default=True)
    return wh


def _upsert_stock(db: Session, *, warehouse: m.AgentWarehouse, vendor_org_id: int, product_id: int) -> m.AgentStockItem:
    item = (
        db.query(m.AgentStockItem)
        .filter(
            m.AgentStockItem.warehouse_id == warehouse.id,
            m.AgentStockItem.vendor_org_id == vendor_org_id,
            m.AgentStockItem.product_id == product_id,
        )
        .first()
    )
    if item is None:
        item = m.AgentStockItem(
            agent_org_id=warehouse.agent_org_id, warehouse_id=warehouse.id,
            vendor_org_id=vendor_org_id, product_id=product_id,
        )
        db.add(item)
        db.flush()
    return item


def _post_agent_movement(
    db: Session, *, warehouse: m.AgentWarehouse, vendor_org_id: int,
    product_id: int, movement_type: str, qty: int, reference_type: str,
    reference_id: int | None, note: str = "", created_by: int | None = None,
) -> m.AgentStockMovement:
    item = _upsert_stock(db, warehouse=warehouse, vendor_org_id=vendor_org_id, product_id=product_id)
    item.on_hand += qty
    if item.on_hand < 0:
        raise ValueError("Agent stock would go negative")
    row = m.AgentStockMovement(
        agent_org_id=warehouse.agent_org_id, warehouse_id=warehouse.id,
        vendor_org_id=vendor_org_id, product_id=product_id,
        movement_type=movement_type, qty=qty, balance_after=item.on_hand,
        reference_type=reference_type, reference_id=reference_id,
        note=note[:1024], created_by=created_by,
    )
    db.add(row)
    db.flush()
    return row


def receive_sourcing_putaway(
    db: Session, *, sourcing_order: market_m.SourcingOrder,
    warehouse_id: int | None = None, received_by: int | None = None,
) -> m.AgentWarehouse:
    """Sourcing arrival at the agent: per-vendor putaway (§20 x §22).

    product.stock is raised by the market service (storefront pool); this
    keeps the agent's shelf truth per vendor + warehouse.
    """
    wh = ensure_default_agent_warehouse(db, sourcing_order.agent_org_id)
    if warehouse_id:
        target = db.get(m.AgentWarehouse, warehouse_id)
        if target is None or target.agent_org_id != sourcing_order.agent_org_id:
            raise ValueError("Warehouse not found for this agent")
        wh = target
    _post_agent_movement(
        db, warehouse=wh, vendor_org_id=sourcing_order.org_id,
        product_id=sourcing_order.catalog_product_id, movement_type="inbound_receive",
        qty=sourcing_order.qty, reference_type="sourcing_order",
        reference_id=sourcing_order.id,
        note=f"Sourcing arrival {sourcing_order.order_number}", created_by=received_by,
    )
    return wh


def agent_stock(db: Session, *, agent_org_id: int, warehouse_id: int | None = None) -> list[dict[str, Any]]:
    q = db.query(m.AgentStockItem).filter(
        m.AgentStockItem.agent_org_id == agent_org_id, m.AgentStockItem.on_hand != 0
    )
    if warehouse_id:
        q = q.filter(m.AgentStockItem.warehouse_id == warehouse_id)
    rows = q.order_by(m.AgentStockItem.id).all()
    out = []
    for it in rows:
        product = db.get(cm.Product, it.product_id)
        vendor = db.get(im.Organization, it.vendor_org_id)
        out.append({
            "id": it.id, "warehouse_id": it.warehouse_id,
            "vendor_org_id": it.vendor_org_id,
            "vendor_name": vendor.name if vendor else f"Org {it.vendor_org_id}",
            "product_id": it.product_id,
            "product_title": product.title if product else f"Product {it.product_id}",
            "product_image": (product.images or [None])[0] if product else None,
            "on_hand": it.on_hand, "reserved": it.reserved,
            "sellable": it.on_hand - it.reserved,
        })
    return out


# ---------------------------------------------------------------------------
# The fulfillment alert: vendor marks -> agent works the order
# ---------------------------------------------------------------------------

def mark_order_for_agent(
    db: Session, *, order: om.Order, agent_org_id: int,
    vendor_org_id: int, created_by: int | None = None,
) -> m.AgentOrder:
    if order.status not in ("confirmed", "processing"):
        raise ValueError(f"Order {order.id} is {order.status}; confirm it before handing to an agent")
    profile = db.get(m.AgentProfile, agent_org_id)
    if profile is None or profile.status != "active":
        raise ValueError("Agent not found or suspended")
    existing = (
        db.query(m.AgentOrder)
        .filter(m.AgentOrder.order_id == order.id, m.AgentOrder.status.notin_(["cancelled", "returned"]))
        .first()
    )
    if existing:
        raise ValueError("This order is already with an agent")

    customer = db.get(crm_m.Customer, order.customer_id)
    item = db.query(om.OrderItem).filter(om.OrderItem.order_id == order.id).first()
    ao = m.AgentOrder(
        code=_next_code(db, m.AgentOrder, "AGF"),
        agent_org_id=agent_org_id, vendor_org_id=vendor_org_id,
        order_id=order.id,
        product_id=item.product_id if item else 0,
        title=item.title if item else "",
        qty=item.qty if item else 1,
        customer_name=customer.full_name if customer else "",
        customer_phone=customer.phone if customer else "",
        customer_address=customer.address if customer else "",
        customer_city=customer.city if customer else "",
        payment_method=order.payment_method,
        cod_expected=order.total if order.payment_method == "cod" else 0.0,
        created_by=created_by,
    )
    db.add(ao)
    db.flush()
    events.publish(db, "agm.order_marked", {
        "agent_order_id": ao.id, "code": ao.code,
        "agent_org_id": agent_org_id, "vendor_org_id": vendor_org_id,
        "order_id": order.id, "title": ao.title, "qty": ao.qty,
        "customer_name": ao.customer_name, "customer_city": ao.customer_city,
        "cod_expected": ao.cod_expected, "payment_method": ao.payment_method,
    })
    return ao


def _advance_order(db: Session, order: om.Order, target: str) -> None:
    """Step the customer order along its §19 machine toward `target`.

    Walks ONLY the steps after the order's current position, so a fresh
    confirmed order crosses confirmed -> processing -> fulfilled ->
    in_transit -> out_for_delivery -> delivered, while an order already in
    flight just takes the remaining hops.
    """
    chain = {
        "out_for_delivery": ["processing", "fulfilled", "in_transit", "out_for_delivery"],
        "delivered": ["processing", "fulfilled", "in_transit", "out_for_delivery", "delivered"],
        "failed": ["processing", "fulfilled", "in_transit", "out_for_delivery", "failed"],
    }
    steps = chain.get(target, [])
    if order.status == target:
        return
    if order.status in steps:
        remaining = steps[steps.index(order.status) + 1:]
    elif order.status == "confirmed":
        remaining = steps
    else:
        return  # unexpected state — never force a machine backwards
    for step in remaining:
        try:
            order_service.transition_order(db, order, step, actor="agm")
        except ValueError:
            break
        if order.status == target:
            break


def agent_order_action(
    db: Session, ao: m.AgentOrder, action: str, *,
    actor: int | None = None, cod_collected: float | None = None,
    note: str = "", failed_reason: str = "",
) -> m.AgentOrder:
    transitions = {
        "accept": "accepted", "start_call": "calling", "confirm": "confirmed",
        "out_for_delivery": "out_for_delivery", "deliver": "delivered",
        "fail": "failed", "return": "returned", "cancel": "cancelled",
    }
    if action not in transitions:
        raise ValueError(f"Unknown agent action: {action}")
    target = transitions[action]
    allowed = m.AGENT_ORDER_TRANSITIONS.get(ao.status, [])
    if target not in allowed:
        raise ValueError(f"Illegal AGM transition {ao.status} -> {target}")

    old = ao.status
    ao.status = target
    if action == "accept":
        ao.accepted_at = _now()
    if note:
        ao.note = note[:1024]

    order = db.get(om.Order, ao.order_id)

    if action == "out_for_delivery":
        if order is not None:
            _advance_order(db, order, "out_for_delivery")
    if action == "deliver":
        if cod_collected is not None and ao.cod_expected > 0:
            ao.cod_collected = round(max(cod_collected, 0), 2)
        elif ao.cod_expected > 0:
            ao.cod_collected = ao.cod_expected
        ao.collected_at = _now()
        ao.delivered_at = _now()
        if order is not None:
            _advance_order(db, order, "delivered")
            # `delivered` fires the COD auto-capture + ledger waterfall (§24/§26)
    if action == "fail":
        ao.failed_reason = failed_reason[:500]
        if order is not None and order.status == "out_for_delivery":
            try:
                order_service.transition_order(db, order, "failed", actor="agm")
            except ValueError:
                pass
    if action == "return":
        if order is not None:
            for step in ("in_transit", "returned"):
                try:
                    order_service.transition_order(db, order, step, actor="agm")
                    break
                except ValueError:
                    continue

    db.flush()
    events.publish(db, "agm.order_status_changed", {
        "agent_order_id": ao.id, "code": ao.code,
        "agent_org_id": ao.agent_org_id, "vendor_org_id": ao.vendor_org_id,
        "order_id": ao.order_id, "from": old, "to": target,
        "cod_collected": ao.cod_collected,
    })
    return ao


# ---------------------------------------------------------------------------
# Remittance — COD custody (§24)
# ---------------------------------------------------------------------------

def create_remittance(
    db: Session, *, agent_org_id: int, vendor_org_id: int | None = None,
    agent_order_ids: list[int] | None = None, reference: str = "", note: str = "",
) -> m.AgentRemittance:
    q = (
        db.query(m.AgentOrder)
        .filter(
            m.AgentOrder.agent_org_id == agent_org_id,
            m.AgentOrder.status == "delivered",
            m.AgentOrder.remittance_id.is_(None),
            m.AgentOrder.cod_collected > 0,
        )
    )
    if vendor_org_id:
        q = q.filter(m.AgentOrder.vendor_org_id == vendor_org_id)
    if agent_order_ids:
        q = q.filter(m.AgentOrder.id.in_(agent_order_ids))
    orders = q.order_by(m.AgentOrder.id).all()
    if not orders:
        raise ValueError("No delivered COD orders awaiting remittance")

    reg = m.AgentRemittance(
        register_code=_next_code(db, m.AgentRemittance, "AGR"),
        agent_org_id=agent_org_id,
        vendor_org_id=vendor_org_id,
        reference=reference[:120], note=note[:1024],
    )
    db.add(reg)
    db.flush()
    expected = 0.0
    for ao in orders:
        db.add(m.AgentRemittanceLine(
            remittance_id=reg.id, agent_order_id=ao.id, order_id=ao.order_id,
            vendor_org_id=ao.vendor_org_id, expected_amount=ao.cod_collected,
        ))
        ao.remittance_id = reg.id
        expected += ao.cod_collected
    reg.expected_amount = round(expected, 2)
    db.flush()
    events.publish(db, "agm.remittance_created", {
        "remittance_id": reg.id, "register_code": reg.register_code,
        "agent_org_id": agent_org_id, "lines": len(orders),
        "expected_amount": reg.expected_amount,
    })
    return reg


def remit(db: Session, reg: m.AgentRemittance, *, reference: str = "") -> m.AgentRemittance:
    if "remitted" not in m.REMITTANCE_TRANSITIONS.get(reg.status, []):
        raise ValueError(f"Cannot remit a register in status {reg.status}")
    reg.status = "remitted"
    reg.remitted_amount = reg.expected_amount
    reg.remitted_at = _now()
    if reference:
        reg.reference = reference[:120]
    events.publish(db, "agm.remittance_remited", {
        "remittance_id": reg.id, "register_code": reg.register_code,
        "agent_org_id": reg.agent_org_id, "amount": reg.remitted_amount,
    })
    return reg


def reconcile(db: Session, reg: m.AgentRemittance, counted: dict[int, float]) -> m.AgentRemittance:
    """Count the envelope line by line; variance hits the ledger (§24 true-up)."""
    if "reconciled" not in m.REMITTANCE_TRANSITIONS.get(reg.status, []):
        raise ValueError(f"Cannot reconcile a register in status {reg.status}")
    lines = (
        db.query(m.AgentRemittanceLine)
        .filter(m.AgentRemittanceLine.remittance_id == reg.id)
        .all()
    )
    total = 0.0
    for line in lines:
        cnt = counted.get(line.id, line.expected_amount)
        if cnt < 0:
            raise ValueError("Counted amount cannot be negative")
        line.counted_amount = round(cnt, 2)
        total += line.counted_amount
    reg.counted_amount = round(total, 2)
    reg.variance_amount = round(reg.counted_amount - reg.expected_amount, 2)
    reg.status = "reconciled"
    reg.reconciled_at = _now()

    events.publish(db, "agm.remittance_reconciled", {
        "remittance_id": reg.id, "register_code": reg.register_code,
        "agent_org_id": reg.agent_org_id,
        "vendor_org_ids": sorted({l.vendor_org_id for l in lines}),
        "expected_amount": reg.expected_amount,
        "counted_amount": reg.counted_amount,
        "variance_amount": reg.variance_amount,
    })
    return reg


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def serialize_agent_card(db: Session, profile: m.AgentProfile, *, linked_org_id: int | None = None) -> dict[str, Any]:
    org = db.get(im.Organization, profile.org_id)
    wh_count = db.query(m.AgentWarehouse).filter(m.AgentWarehouse.agent_org_id == profile.org_id).count()
    return {
        "agent_org_id": profile.org_id,
        "company": org.name if org else f"Agent {profile.org_id}",
        "contact_name": profile.contact_name,
        "phone": profile.phone,
        "whatsapp": profile.whatsapp,
        "city": profile.city,
        "country": profile.country,
        "address": profile.address,
        "capacity_note": profile.capacity_note,
        "rating": profile.rating,
        "warehouses": wh_count,
        "status": profile.status,
        "linked": linked_org_id is not None,
        "link_status": None,  # filled by callers when a link exists
    }


def serialize_agent_order(ao: m.AgentOrder) -> dict[str, Any]:
    return {
        "id": ao.id, "code": ao.code,
        "agent_org_id": ao.agent_org_id, "vendor_org_id": ao.vendor_org_id,
        "order_id": ao.order_id, "product_id": ao.product_id, "title": ao.title,
        "qty": ao.qty,
        "customer": {
            "name": ao.customer_name, "phone": ao.customer_phone,
            "address": ao.customer_address, "city": ao.customer_city,
        },
        "payment_method": ao.payment_method,
        "cod_expected": ao.cod_expected, "cod_collected": ao.cod_collected,
        "collected_at": ao.collected_at.isoformat() if ao.collected_at else None,
        "remittance_id": ao.remittance_id,
        "status": ao.status, "note": ao.note, "failed_reason": ao.failed_reason,
        "accepted_at": ao.accepted_at.isoformat() if ao.accepted_at else None,
        "delivered_at": ao.delivered_at.isoformat() if ao.delivered_at else None,
        "created_at": ao.created_at.isoformat() if ao.created_at else None,
        "allowed_transitions": m.AGENT_ORDER_TRANSITIONS.get(ao.status, []),
    }


def serialize_remittance(db: Session, reg: m.AgentRemittance, *, with_lines: bool = False) -> dict[str, Any]:
    data = {
        "id": reg.id, "register_code": reg.register_code,
        "agent_org_id": reg.agent_org_id, "vendor_org_id": reg.vendor_org_id,
        "status": reg.status, "currency": reg.currency,
        "expected_amount": reg.expected_amount,
        "remitted_amount": reg.remitted_amount,
        "counted_amount": reg.counted_amount,
        "variance_amount": reg.variance_amount,
        "reference": reg.reference, "note": reg.note,
        "remitted_at": reg.remitted_at.isoformat() if reg.remitted_at else None,
        "reconciled_at": reg.reconciled_at.isoformat() if reg.reconciled_at else None,
        "created_at": reg.created_at.isoformat() if reg.created_at else None,
    }
    if with_lines:
        lines = (
            db.query(m.AgentRemittanceLine)
            .filter(m.AgentRemittanceLine.remittance_id == reg.id)
            .all()
        )
        data["lines"] = [
            {
                "id": l.id, "agent_order_id": l.agent_order_id,
                "order_id": l.order_id, "vendor_org_id": l.vendor_org_id,
                "expected_amount": l.expected_amount,
                "counted_amount": l.counted_amount,
            }
            for l in lines
        ]
    return data
