"""Market service — Marketstore pricing, sourcing orders, review gate (§8-11).

Corridor flows this module owns:

  Supplier upload     -> submit -> Luxeen REVIEW GATE -> publish
                      (publish normalises the supplier product into a
                       canonical catalog Product — one product, one
                       environment, §10/§51)

  Operator sources    -> supply quote in local currency (§46 FX snapshot)
                      -> prepaid sourcing order routed to the supplier

  Supplier fulfils    -> accept -> checkpoint updates on the §23 ladder

  Arrival             -> receive: AGM agent putaway (per-vendor stock) or
                         the operator's own warehouse (§22)

Isolation helpers (§9) keep every payload one-sided: the operator never
sees the supplier, the supplier never sees the operator.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.agm import models as agm_m
from app.catalog import models as cm
from app.core import events
from app.finance import economics
from app.finance import fx as fx_service
from app.logistics import rates as rates_service
from app.market import models as m
from app.supply import models as sm

REVIEW_LADDER_CODES = list(m.SOURCING_CODE_MAP.keys())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _next_sourcing_number(db: Session) -> str:
    last = db.query(m.SourcingOrder).order_by(m.SourcingOrder.id.desc()).first()
    return f"SRC-{(last.id if last else 0) + 1:05d}"


def _unique_slug(db: Session, title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (title or "product").lower()).strip("-") or "product"
    slug, n = base, 2
    while db.query(cm.Product).filter(cm.Product.slug == slug).first():
        slug = f"{base}-{n}"
        n += 1
    return slug


# ---------------------------------------------------------------------------
# Pricing — the supply price an operator pays on the Marketstore (§12, §46)
# ---------------------------------------------------------------------------

def supply_quote(db: Session, sp: m.SupplierProduct, *, qty: int = 1,
                 org_id: int | None = None) -> dict[str, Any]:
    """Cost waterfall for one sourcing line, in the operator's local currency.

    Marketstore price = supplier cost (converted) + intl freight (§21 rate
    card for the lane, profile per-kg fallback) + payment cost + Luxeen
    economics. No retail markup — the buyer IS the
    operator; their own markup applies later in their storefront (§12).
    """
    conv = fx_service.convert(db, float(sp.cost_price), sp.currency or "CNY", "NGN")
    supplier_ngn = float(conv["amount"])
    rate = float(conv["rate"])
    profile = economics.resolve_profile(
        db, org_id=org_id, origin="CN", dest="NG", category=sp.category,
    )
    card = rates_service.resolve_rate(db, origin="CN", dest="NG", org_id=org_id)
    freight = rates_service.freight_cost(
        card, declared_value_ngn=supplier_ngn * qty,
        weight_total_kg=float(sp.weight_kg) * qty,
    ) if card else None

    if freight:
        logistics = freight["freight_ngn"] + freight["customs_ngn"]
        card_label = f"{card['name']} ({card['mode']})"
    else:
        logistics = profile["logistics_per_kg_ngn"] * float(sp.weight_kg) * qty
        logistics += supplier_ngn * qty * profile.get("tax_pct", 0.0)
        card_label = "profile per-kg"
    payment = (supplier_ngn * qty + logistics) * profile["payment_cost_pct"]
    luxeen = supplier_ngn * qty * profile["luxeen_margin_pct"]
    total = _round5(supplier_ngn * qty + logistics + payment + luxeen)
    lead = None
    if card:
        lead = (int(card["lead_time_days_min"]) + int(card["lead_time_days_max"])) // 2
    return {
        "unit_supplier_cost_original": float(sp.cost_price),
        "currency_original": sp.currency or "CNY",
        "fx_rate": rate,
        "fx_source": conv["source"],
        "unit_supplier_ngn": round(supplier_ngn, 2),
        "logistics_ngn": round(logistics, 2),
        "freight_ngn": round(freight["freight_ngn"], 2) if freight else round(logistics, 2),
        "customs_ngn": round(freight["customs_ngn"], 2) if freight else 0.0,
        "payment_ngn": round(payment, 2),
        "luxeen_ngn": round(luxeen, 2),
        "unit_supply_price_ngn": _round5(supplier_ngn + logistics / qty + payment / qty + luxeen / qty),
        "total_supply_price_ngn": total,
        "lead_time_days": lead,
        "economics": {
            "profile_id": profile["profile_id"],
            "profile_name": profile["profile_name"],
            "rate_card": card_label,
            "rate_card_id": card["id"] if card else None,
        },
        # §21: the lane's other modes, so the buyer sees air vs sea honestly
        "lane_options": rates_service.lane_options(db, origin="CN", dest="NG", org_id=org_id),
    }


def _round5(v: float) -> float:
    return round(v / 5) * 5


# ---------------------------------------------------------------------------
# Supplier portal — upload -> submit -> review -> publish (§8)
# ---------------------------------------------------------------------------

def create_supplier_product(db: Session, *, supplier_id: int, org_id: int | None, **fields) -> m.SupplierProduct:
    sp = m.SupplierProduct(
        supplier_id=supplier_id, org_id=org_id,
        title=(fields.get("title") or "").strip()[:255],
        description=fields.get("description") or "",
        category=fields.get("category") or "general",
        industry=fields.get("industry") or "",
        cost_price=float(fields.get("cost_price") or 0),
        currency=(fields.get("currency") or "CNY").upper(),
        weight_kg=float(fields.get("weight_kg") or 0.5),
        moq=max(int(fields.get("moq") or 1), 1),
        images=fields.get("images") or [],
        specs=fields.get("specs") or {},
        status="draft",
    )
    if not sp.title:
        raise ValueError("Title is required")
    if sp.cost_price <= 0:
        raise ValueError("cost_price must be positive")
    db.add(sp)
    db.flush()
    events.publish(db, "market.product_uploaded", {
        "supplier_product_id": sp.id, "supplier_id": supplier_id,
        "title": sp.title, "status": sp.status,
    })
    return sp


def submit_for_review(db: Session, sp: m.SupplierProduct) -> m.SupplierProduct:
    _transition_product(db, sp, "submitted")
    sp.submitted_at = _now()
    events.publish(db, "market.product_submitted", {
        "supplier_product_id": sp.id, "title": sp.title,
        "supplier_id": sp.supplier_id,
    })
    return sp


def review_product(
    db: Session, sp: m.SupplierProduct, *, decision: str,
    notes: str = "", reviewed_by: int | None = None,
) -> m.SupplierProduct:
    """The Luxeen quality gate (§8 verification): approve or reject."""
    if decision not in ("approve", "reject"):
        raise ValueError("decision must be approve|reject")
    target = "approved" if decision == "approve" else "rejected"
    _transition_product(db, sp, target)
    sp.review_notes = notes[:1024]
    sp.reviewed_at = _now()
    sp.reviewed_by = reviewed_by
    events.publish(db, "market.product_reviewed", {
        "supplier_product_id": sp.id, "decision": decision,
        "supplier_id": sp.supplier_id,
    })
    return sp


def publish_product(db: Session, sp: m.SupplierProduct, *, published_by: int | None = None) -> m.SupplierProduct:
    """Approved -> published: normalise into the canonical catalog (§10).

    The catalog Product starts with stock 0 — units only enter the sellable
    pool when a sourcing order physically arrives (restock-first corridor).
    """
    _transition_product(db, sp, "published")
    if sp.catalog_product_id is None:
        product = cm.Product(
            supplier_id=sp.supplier_id,
            slug=_unique_slug(db, sp.title),
            title=sp.title,
            description=sp.description,
            category=sp.category or "general",
            currency=sp.currency or "CNY",
            supplier_cost=float(sp.cost_price),
            weight_kg=float(sp.weight_kg),
            status="active",
            stock=0,
            country_of_origin="CN",
            images=sp.images or [],
            specs=sp.specs or {},
        )
        db.add(product)
        db.flush()
        sp.catalog_product_id = product.id
    else:
        product = db.get(cm.Product, sp.catalog_product_id)
        if product is not None:
            product.status = "active"
    sp.published_at = _now()
    events.publish(db, "market.product_published", {
        "supplier_product_id": sp.id, "catalog_product_id": sp.catalog_product_id,
        "title": sp.title,
    })
    return sp


def _transition_product(db: Session, sp: m.SupplierProduct, new_status: str) -> None:
    allowed = m.SUPPLIER_PRODUCT_TRANSITIONS.get(sp.status, [])
    if new_status not in allowed:
        raise ValueError(f"Illegal supplier-product transition {sp.status} -> {new_status}")
    sp.status = new_status
    db.flush()


# ---------------------------------------------------------------------------
# Sourcing orders — operator buys, supplier fulfils (§11, §20, §23)
# ---------------------------------------------------------------------------

def create_sourcing_order(
    db: Session,
    *,
    supplier_product_id: int,
    org_id: int,
    qty: int,
    created_by: int | None = None,
    agent_org_id: int | None = None,
    dest_name: str = "",
    dest_phone: str = "",
    dest_address: str = "",
    dest_city: str = "",
    dest_country: str = "NG",
    note: str = "",
) -> m.SourcingOrder:
    sp = db.get(m.SupplierProduct, supplier_product_id)
    if sp is None or sp.status != "published":
        raise ValueError("This product is not available on the Marketstore")
    if qty < sp.moq:
        raise ValueError(f"Minimum order quantity is {sp.moq}")

    quote = supply_quote(db, sp, qty=qty, org_id=org_id)
    card_snapshot = rates_service.resolve_rate(db, origin="CN", dest="NG", org_id=org_id)
    agent_wh = None
    if agent_org_id:
        agent_wh = agm_service.ensure_default_agent_warehouse(db, agent_org_id)
        if dest_name == "":
            dest_name = f"Agent warehouse ({agent_wh.name})"
            dest_address = agent_wh.address or dest_address
            dest_city = agent_wh.city or dest_city
            dest_country = agent_wh.country or dest_country

    so = m.SourcingOrder(
        order_number=_next_sourcing_number(db), org_id=org_id,
        supplier_id=sp.supplier_id, supplier_product_id=sp.id,
        catalog_product_id=sp.catalog_product_id,
        title=sp.title, unit_cost_cny=float(sp.cost_price), qty=qty,
        cny_total=round(float(sp.cost_price) * qty, 2),
        fx_rate=quote["fx_rate"], local_currency="NGN",
        local_total=quote["total_supply_price_ngn"],
        weight_kg=float(sp.weight_kg),
        rate_card_snapshot=card_snapshot,
        agent_org_id=agent_org_id,
        dest_name=dest_name[:255], dest_phone=dest_phone[:50],
        dest_address=dest_address[:1024], dest_city=dest_city[:100],
        dest_country=dest_country[:2],
        supplier_note=note[:1024], created_by=created_by,
    )
    db.add(so)
    db.flush()
    db.add(m.SourcingEvent(
        sourcing_order_id=so.id, code="supplier_processing",
        description="Order placed on the Ecos Marketstore — awaiting supplier confirmation.",
        location="Ecos Network",
    ))
    events.publish(db, "sourcing.created", {
        "sourcing_order_id": so.id, "order_number": so.order_number,
        "org_id": org_id, "supplier_id": so.supplier_id,
        "qty": qty, "local_total": so.local_total,
    })
    return so


def pay_sourcing_order(
    db: Session, so: m.SourcingOrder, *, method: str = "wallet",
    reference: str = "", actor: int | None = None,
) -> m.SourcingOrder:
    """Prepaid stock (default 1): operator pays Ecos; money hits the ledger
    via the `sourcing.paid` subscriber (§26) and the supplier is alerted."""
    if so.status != "pending_payment":
        raise ValueError(f"Sourcing order {so.order_number} is {so.status}, not awaiting payment")
    sp = db.get(m.SupplierProduct, so.supplier_product_id)
    sp_category = sp.category if sp else None
    so.status = "paid"
    so.payment_method = method
    so.payment_reference = reference or f"SRC-PAY-{so.id:08d}"
    so.paid_at = _now()
    events.publish(db, "sourcing.paid", {
        "sourcing_order_id": so.id, "order_number": so.order_number,
        "org_id": so.org_id, "supplier_id": so.supplier_id,
        "amount_ngn": so.local_total, "cny_total": so.cny_total,
        "fx_rate": so.fx_rate, "weight_kg": so.weight_kg, "qty": so.qty,
        "method": so.payment_method,
        "category": sp_category, "rate_card": so.rate_card_snapshot,
    })
    events.publish(db, "sourcing.submitted", {
        "sourcing_order_id": so.id, "order_number": so.order_number,
        "supplier_id": so.supplier_id, "title": so.title,
        "qty": so.qty, "cny_total": so.cny_total,
        "dest_city": so.dest_city, "dest_country": so.dest_country,
        "note": so.supplier_note,
    })
    return so


def cancel_sourcing_order(db: Session, so: m.SourcingOrder) -> m.SourcingOrder:
    if so.status in ("arrived", "received"):
        raise ValueError("Goods already arrived — use returns instead")
    if so.status == "cancelled":
        return so
    so.status = "cancelled"
    so.cancelled_at = _now()
    events.publish(db, "sourcing.cancelled", {
        "sourcing_order_id": so.id, "order_number": so.order_number,
        "org_id": so.org_id,
    })
    return so


def add_sourcing_event(
    db: Session, so: m.SourcingOrder, *, code: str,
    description: str = "", location: str = "",
) -> m.SourcingEvent:
    """Supplier-side checkpoint update on the §23 ladder."""
    if code not in m.SOURCING_CODE_MAP:
        raise ValueError(f"Unknown tracking code: {code}")
    if so.status in ("pending_payment", "cancelled"):
        raise ValueError("Order is not active for tracking updates")
    event = m.SourcingEvent(
        sourcing_order_id=so.id, code=code,
        description=description[:1024], location=location[:255],
    )
    db.add(event)
    target = m.SOURCING_CODE_MAP[code]
    if target in m.SOURCING_TRANSITIONS.get(so.status, []) :
        so.status = target
    db.flush()
    events.publish(db, "sourcing.status_changed", {
        "sourcing_order_id": so.id, "order_number": so.order_number,
        "org_id": so.org_id, "supplier_id": so.supplier_id,
        "code": code, "status": so.status,
        "location": location, "description": description,
    })
    return event


def receive_sourcing_order(
    db: Session, so: m.SourcingOrder, *, received_by: int | None = None,
    warehouse_id: int | None = None,
) -> dict[str, Any]:
    """Goods arrived in Nigeria: put the units where they belong.

    - With an agent destination: AGM per-vendor putaway (agent holds the
      vendor's stock) AND product.stock rises so the storefront pool grows.
    - Without an agent: straight into the operator's default warehouse (§22).
    """
    if so.status != "arrived":
        raise ValueError(f"Sourcing order {so.order_number} is {so.status}; must be arrived to receive")

    product = db.get(cm.Product, so.catalog_product_id) if so.catalog_product_id else None
    if product is None:
        raise ValueError("Sourcing order has no linked catalog product")

    result: dict[str, Any] = {"mode": "operator_warehouse"}
    if so.agent_org_id:
        from app.agm import service as agm_service  # local import: avoid cycle

        agent_wh = agm_service.receive_sourcing_putaway(
            db, sourcing_order=so, warehouse_id=warehouse_id, received_by=received_by,
        )
        result = {"mode": "agent_putaway", "agent_warehouse": agent_wh.name}
    else:
        from app.warehouse import service as warehouse_service

        wh = warehouse_service.ensure_default_warehouse(db, warehouse_id if warehouse_id else so.org_id)
        warehouse_service.receive_stock(
            db, warehouse=wh, product=product, qty=so.qty,
            reference_type="sourcing_order", reference_id=so.id,
            note=f"Sourcing arrival {so.order_number}", created_by=received_by,
        )
        result["warehouse"] = wh.name

    product.stock += so.qty  # the storefront oversell pool grows by the arrived units
    so.status = "received"
    so.received_at = _now()
    so.received_by = received_by
    db.flush()
    events.publish(db, "sourcing.received", {
        "sourcing_order_id": so.id, "order_number": so.order_number,
        "org_id": so.org_id, "agent_org_id": so.agent_org_id,
        "qty": so.qty, "mode": result["mode"], "product_id": product.id,
    })
    return result


# ---------------------------------------------------------------------------
# Serializers — isolation lives here (§9)
# ---------------------------------------------------------------------------

def serialize_listing(db: Session, sp: m.SupplierProduct) -> dict[str, Any]:
    """MARKETSTORE view — what operators see. Zero supplier identity."""
    quote = supply_quote(db, sp)
    # the quote box only renders scalar components — structured extras go flat
    pricing = {
        k: v for k, v in quote.items()
        if k not in ("economics", "lane_options") and not isinstance(v, (dict, list))
    }
    return {
        "id": sp.id,
        "catalog_product_id": sp.catalog_product_id,
        "title": sp.title,
        "description": sp.description,
        "category": sp.category,
        "industry": sp.industry,
        "images": sp.images or [],
        "specs": sp.specs or {},
        "moq": sp.moq,
        "weight_kg": sp.weight_kg,
        "currency": "NGN",
        "unit_price": quote["unit_supply_price_ngn"],
        "pricing": pricing,
        "economics": quote["economics"],
        "lane_options": quote["lane_options"],
        "available_from": "Ecos Network",
        "lead_time_days": quote.get("lead_time_days") or 14,
    }


def serialize_sourcing_operator(db: Session, so: m.SourcingOrder, *, with_events: bool = False) -> dict[str, Any]:
    """OPERATOR view of a sourcing order — no supplier fields whatsoever."""
    data = {
        "id": so.id,
        "order_number": so.order_number,
        "title": so.title,
        "qty": so.qty,
        "cny_total": so.cny_total,      # transparency of the corridor cost
        "fx_rate": so.fx_rate,
        "local_currency": so.local_currency,
        "local_total": so.local_total,
        "status": so.status,
        "payment_method": so.payment_method,
        "payment_reference": so.payment_reference,
        "paid_at": so.paid_at.isoformat() if so.paid_at else None,
        "destination": {
            "name": so.dest_name, "phone": so.dest_phone,
            "address": so.dest_address, "city": so.dest_city,
            "country": so.dest_country,
            "via_agent": bool(so.agent_org_id),
        },
        "supplier_note": so.supplier_note,
        "received_at": so.received_at.isoformat() if so.received_at else None,
        "catalog_product_id": so.catalog_product_id,
        "created_at": so.created_at.isoformat() if so.created_at else None,
        "allowed_transitions": m.SOURCING_TRANSITIONS.get(so.status, []),
    }
    if with_events:
        rows = (
            db.query(m.SourcingEvent)
            .filter(m.SourcingEvent.sourcing_order_id == so.id)
            .order_by(m.SourcingEvent.id)
            .all()
        )
        data["events"] = [
            {
                "id": e.id, "code": e.code, "description": e.description,
                "location": e.location,
                "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
            }
            for e in rows
        ]
    return data


def serialize_sourcing_supplier(db: Session, so: m.SourcingOrder, *, with_events: bool = False) -> dict[str, Any]:
    """SUPPLIER view — what to prepare and where to ship. No buyer identity."""
    data = {
        "id": so.id,
        "order_number": so.order_number,
        "title": so.title,
        "qty": so.qty,
        "unit_cost_cny": so.unit_cost_cny,
        "cny_total": so.cny_total,
        "status": so.status,
        "destination": {
            "name": so.dest_name, "phone": so.dest_phone,
            "address": so.dest_address, "city": so.dest_city,
            "country": so.dest_country,
        },
        "note": so.supplier_note,
        "paid_at": so.paid_at.isoformat() if so.paid_at else None,
        "created_at": so.created_at.isoformat() if so.created_at else None,
    }
    if with_events:
        rows = (
            db.query(m.SourcingEvent)
            .filter(m.SourcingEvent.sourcing_order_id == so.id)
            .order_by(m.SourcingEvent.id)
            .all()
        )
        data["events"] = [
            {
                "id": e.id, "code": e.code, "description": e.description,
                "location": e.location,
                "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
            }
            for e in rows
        ]
    return data


def serialize_supplier_product(sp: m.SupplierProduct, *, supplier_view: bool = False) -> dict[str, Any]:
    data = {
        "id": sp.id,
        "title": sp.title,
        "description": sp.description,
        "category": sp.category,
        "industry": sp.industry,
        "cost_price": sp.cost_price,
        "currency": sp.currency,
        "weight_kg": sp.weight_kg,
        "moq": sp.moq,
        "images": sp.images or [],
        "specs": sp.specs or {},
        "status": sp.status,
        "review_notes": sp.review_notes,
        "catalog_product_id": sp.catalog_product_id,
        "submitted_at": sp.submitted_at.isoformat() if sp.submitted_at else None,
        "reviewed_at": sp.reviewed_at.isoformat() if sp.reviewed_at else None,
        "published_at": sp.published_at.isoformat() if sp.published_at else None,
        "created_at": sp.created_at.isoformat() if sp.created_at else None,
    }
    if supplier_view:
        data["allowed_transitions"] = m.SUPPLIER_PRODUCT_TRANSITIONS.get(sp.status, [])
    return data


# lazy import alias so create_sourcing_order can call agm service cleanly
from app.agm import service as agm_service  # noqa: E402  (placed last: cycle-safe)
