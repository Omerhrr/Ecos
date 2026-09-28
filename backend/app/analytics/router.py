"""Analytics across the commerce lifecycle (plan §29).

Phase 1 exposes business, product, and funnel aggregates computed directly
from the domain tables. Phase 2 adds the three operator suites — logistics
(delivery performance), financial (contribution economics), and product
(margin / returns / stock cover) — still computed live from domain data.
As volume grows these move to a warehouse / the network intelligence
layer (§48).
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_perm
from app.crm import models as cm
from app.finance import models as fm
from app.logistics import models as lm
from app.orders import models as om
from app.returns import models as rm
from app.payments import models as pm
from app.settlements import service as settlement_service

router = APIRouter(
    prefix="/analytics", tags=["analytics"],
    dependencies=[Depends(require_perm("analytics:read"))],
)


def _naive_utc(dt: datetime) -> datetime:
    """SQLite stores naive datetimes — compare apples to apples (UTC)."""
    return dt.replace(tzinfo=None) if dt.tzinfo is None else dt.astimezone(timezone.utc).replace(tzinfo=None)


def _since(days: int) -> datetime:
    return _naive_utc(datetime.now(timezone.utc) - timedelta(days=max(1, days)))


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    total_orders = db.query(sa_func.count(om.Order.id)).scalar() or 0
    delivered = (
        db.query(sa_func.count(om.Order.id)).filter(om.Order.status == "delivered").scalar() or 0
    )
    in_flight = (
        db.query(sa_func.count(om.Order.id))
        .filter(om.Order.status.in_(["confirmed", "processing", "fulfilled", "in_transit", "out_for_delivery"]))
        .scalar() or 0
    )
    cancelled = (
        db.query(sa_func.count(om.Order.id))
        .filter(om.Order.status.in_(["cancelled", "failed", "returned", "refunded"]))
        .scalar() or 0
    )
    revenue = (
        db.query(sa_func.coalesce(sa_func.sum(pm.Payment.amount), 0.0))
        .filter(pm.Payment.status == "paid")
        .scalar() or 0.0
    )
    cod_pending = (
        db.query(sa_func.coalesce(sa_func.sum(pm.Payment.amount), 0.0))
        .filter(pm.Payment.method == "cod", pm.Payment.status == "pending")
        .scalar() or 0.0
    )
    orders_count = total_orders or 1
    aov = revenue / max(
        db.query(sa_func.count(pm.Payment.id)).filter(pm.Payment.status == "paid").scalar() or 1, 1
    )
    total_leads = db.query(sa_func.count(cm.Lead.id)).scalar() or 0
    active_leads = (
        db.query(sa_func.count(cm.Lead.id))
        .filter(cm.Lead.status.in_(["new", "contacted", "interested"]))
        .scalar() or 0
    )
    return {
        "revenue_ngn": round(revenue, 2),
        "cod_pending_ngn": round(cod_pending, 2),
        "orders_total": total_orders,
        "orders_delivered": delivered,
        "orders_in_flight": in_flight,
        "orders_problem": cancelled,
        "delivery_rate": round(delivered / orders_count, 4) if total_orders else 0.0,
        "aov_ngn": round(aov, 2),
        "leads_total": total_leads,
        "leads_active": active_leads,
        "lead_conversion": round(total_orders / total_leads, 4) if total_leads else 0.0,
    }


@router.get("/funnel")
def funnel(db: Session = Depends(get_db)):
    by_status = dict(
        db.query(cm.Lead.status, sa_func.count(cm.Lead.id)).group_by(cm.Lead.status).all()
    )
    pipeline = ["new", "contacted", "interested", "order_created", "confirmed", "fulfilled", "delivered"]
    exit_status = ["unreachable", "cancelled", "returned", "refunded"]
    return {
        "pipeline": [{"status": s, "count": by_status.get(s, 0)} for s in pipeline],
        "exits": [{"status": s, "count": by_status.get(s, 0)} for s in exit_status],
    }


@router.get("/top-products")
def top_products(db: Session = Depends(get_db)):
    rows = (
        db.query(
            om.OrderItem.product_id,
            om.OrderItem.title,
            sa_func.sum(om.OrderItem.qty).label("units"),
            sa_func.sum(om.OrderItem.qty * om.OrderItem.unit_price).label("revenue"),
        )
        .join(om.Order, om.Order.id == om.OrderItem.order_id)
        .group_by(om.OrderItem.product_id, om.OrderItem.title)
        .order_by(sa_func.sum(om.OrderItem.qty * om.OrderItem.unit_price).desc())
        .limit(8)
        .all()
    )
    return [
        {"product_id": r.product_id, "title": r.title, "units": int(r.units), "revenue_ngn": round(float(r.revenue), 2)}
        for r in rows
    ]


# --------------------------------------------------------------------------
# §29 suite 1 — Logistics: delivery performance, carrier leaderboard, stalls
# --------------------------------------------------------------------------

@router.get("/logistics")
def logistics_suite(days: int = 30, db: Session = Depends(get_db)):
    since = _since(days)
    shipments = (
        db.query(lm.Shipment)
        .filter(lm.Shipment.created_at >= since)
        .all()
    )
    now = _naive_utc(datetime.now(timezone.utc))
    per_carrier: dict[str, dict] = {}
    transit_hours: list[float] = []
    stalled: list[dict] = []
    active_states = ("processing", "in_transit", "out_for_delivery")

    for s in shipments:
        c = per_carrier.setdefault(s.carrier, {
            "carrier": s.carrier, "shipments": 0, "delivered": 0,
            "active": 0, "avg_transit_hours": None,
        })
        c["shipments"] += 1
        if s.status == "delivered" and s.delivered_at:
            c["delivered"] += 1
            hours = (s.delivered_at - s.created_at).total_seconds() / 3600
            transit_hours.append(hours)
        elif s.status in active_states:
            c["active"] += 1
        last = (
            db.query(lm.TrackingEvent)
            .filter(lm.TrackingEvent.shipment_id == s.id)
            .order_by(lm.TrackingEvent.occurred_at.desc(), lm.TrackingEvent.id.desc())
            .first()
        )
        if s.status in active_states and (last is None or last.occurred_at is None or
                                          (now - last.occurred_at).total_seconds() / 3600 >= 48):
            stalled.append({"shipment_id": s.id, "order_id": s.order_id,
                            "tracking_code": s.tracking_code,
                            "last_checkpoint": last.code if last else None})

    avg_transit = round(sum(transit_hours) / len(transit_hours), 1) if transit_hours else None
    for c in per_carrier.values():
        c["delivered_share"] = round(c["delivered"] / c["shipments"], 3) if c["shipments"] else 0.0
    carriers = sorted(per_carrier.values(), key=lambda c: (-c["shipments"], c["carrier"]))

    rma_shipments = 0  # reverse-flow share (§21/§28): checkpoints in return codes
    total_checkpoints = (
        db.query(sa_func.count(lm.TrackingEvent.id))
        .join(lm.Shipment, lm.Shipment.id == lm.TrackingEvent.shipment_id)
        .filter(lm.Shipment.created_at >= since)
        .scalar() or 0
    )
    reverse_checkpoints = (
        db.query(sa_func.count(lm.TrackingEvent.id))
        .join(lm.Shipment, lm.Shipment.id == lm.TrackingEvent.shipment_id)
        .filter(lm.Shipment.created_at >= since,
                lm.TrackingEvent.code.in_(["return_requested", "return_pickup", "return_received"]))
        .scalar() or 0
    )
    rma_shipments = reverse_checkpoints

    return {
        "window_days": days,
        "shipments_total": len(shipments),
        "shipments_delivered": sum(c["delivered"] for c in carriers),
        "shipments_active": sum(c["active"] for c in carriers),
        "avg_transit_hours": avg_transit,
        "stalled_over_48h": stalled,
        "carriers": carriers,
        "reverse_checkpoints": rma_shipments,
        "checkpoint_total": total_checkpoints,
    }


# --------------------------------------------------------------------------
# §29 suite 2 — Financial: contribution economics from the immutable ledger
# --------------------------------------------------------------------------

@router.get("/financial")
def financial_suite(days: int = 30, db: Session = Depends(get_db)):
    since = _since(days)
    by_type = dict(
        db.query(fm.LedgerEntry.entry_type, sa_func.sum(fm.LedgerEntry.amount))
        .filter(fm.LedgerEntry.created_at >= since)
        .group_by(fm.LedgerEntry.entry_type)
        .all()
    )
    by_type = {k: round(float(v or 0.0), 2) for k, v in by_type.items()}

    gross = by_type.get("customer_payment", 0.0)
    refunds = by_type.get("refund", 0.0)  # pre-signed negative
    supplier = abs(by_type.get("supplier_payable", 0.0))
    logistics = abs(by_type.get("logistics_cost", 0.0))
    paycost = abs(by_type.get("payment_cost", 0.0))
    luxeen = abs(by_type.get("luxeen_economics", 0.0))
    operator = by_type.get("operator_economics", 0.0)
    net = gross + refunds
    contribution = net - supplier - logistics - paycost - luxeen

    payments_total = (
        db.query(sa_func.count(pm.Payment.id))
        .filter(pm.Payment.created_at >= since)
        .scalar() or 0
    )
    cod_collected = (
        db.query(sa_func.coalesce(sa_func.sum(pm.Payment.amount), 0.0))
        .filter(pm.Payment.created_at >= since, pm.Payment.method == "cod", pm.Payment.status == "paid")
        .scalar() or 0.0
    )
    cod_pending = (
        db.query(sa_func.coalesce(sa_func.sum(pm.Payment.amount), 0.0))
        .filter(pm.Payment.method == "cod", pm.Payment.status == "pending")
        .scalar() or 0.0
    )
    try:
        unsettled = settlement_service.unsettled_summary(db)
    except Exception:  # noqa: BLE001
        unsettled = {"total_amount": 0.0, "entry_count": 0, "lines": []}

    return {
        "window_days": days,
        "ledger_totals_by_type": by_type,
        "gross_revenue_ngn": round(gross, 2),
        "refunds_ngn": round(refunds, 2),
        "net_revenue_ngn": round(net, 2),
        "supplier_cost_ngn": round(supplier, 2),
        "logistics_cost_ngn": round(logistics, 2),
        "payment_cost_ngn": round(paycost, 2),
        "luxeen_economics_ngn": round(luxeen, 2),
        "operator_economics_ngn": round(operator, 2),
        "contribution_ngn": round(contribution, 2),
        "contribution_margin_pct": round(contribution / net, 4) if net else 0.0,
        "cod_collected_ngn": round(cod_collected, 2),
        "cod_pending_ngn": round(cod_pending, 2),
        "payments_count": payments_total,
        "unsettled_obligations": {
            "amount": unsettled.get("total_amount", 0.0),
            "entries": unsettled.get("entry_count", 0),
            "lines": unsettled.get("lines", [])[:10],
        },
    }


# --------------------------------------------------------------------------
# §29 suite 3 — Product: units, margin, return rate, stock cover per SKU
# --------------------------------------------------------------------------

@router.get("/products")
def product_suite(days: int = 30, db: Session = Depends(get_db)):
    from app.catalog import models as cat_m
    from app.core.pricing import FX_RATES

    cny_rate = FX_RATES["CNY"]["NGN"]
    since = _since(days)

    rows = (
        db.query(
            om.OrderItem.product_id,
            om.OrderItem.title,
            sa_func.sum(om.OrderItem.qty).label("units"),
            sa_func.sum(om.OrderItem.qty * om.OrderItem.unit_price).label("revenue"),
            sa_func.sum(om.OrderItem.qty * om.OrderItem.supplier_cost_cny).label("cost_cny"),
        )
        .join(om.Order, om.Order.id == om.OrderItem.order_id)
        .filter(om.Order.created_at >= since,
                om.Order.status.notin_(["draft", "cancelled", "failed"]))
        .group_by(om.OrderItem.product_id, om.OrderItem.title)
        .all()
    )

    return_units: dict[int, int] = {}
    rma_rows = (
        db.query(om.OrderItem.product_id, sa_func.sum(om.OrderItem.qty))
        .join(om.Order, om.Order.id == om.OrderItem.order_id)
        .join(rm.ReturnOrder, rm.ReturnOrder.order_id == om.Order.id)
        .filter(rm.ReturnOrder.created_at >= since)
        .group_by(om.OrderItem.product_id)
        .all()
    )
    for pid, units in rma_rows:
        return_units[pid] = int(units or 0)

    products = {p.id: p for p in db.query(cat_m.Product).all()}
    out = []
    for r in rows:
        p = products.get(r.product_id)
        units = int(r.units or 0)
        revenue = float(r.revenue or 0.0)
        cost_ngn = float(r.cost_cny or 0.0) * cny_rate
        margin = revenue - cost_ngn
        velocity_per_week = units / max(days / 7.0, 0.1)
        stock = p.stock if p else 0
        out.append({
            "product_id": r.product_id,
            "title": r.title,
            "units_sold": units,
            "revenue_ngn": round(revenue, 2),
            "supplier_cost_ngn": round(cost_ngn, 2),
            "gross_margin_ngn": round(margin, 2),
            "margin_per_unit_ngn": round(margin / units, 2) if units else 0.0,
            "return_units": return_units.get(r.product_id, 0),
            "return_rate": round(return_units.get(r.product_id, 0) / units, 3) if units else 0.0,
            "stock_on_hand": stock,
            "weekly_velocity": round(velocity_per_week, 2),
            "weeks_of_cover": round(stock / velocity_per_week, 1) if velocity_per_week else None,
            "status": p.status if p else None,
        })
    out.sort(key=lambda r: -r["revenue_ngn"])

    catalog_count = db.query(sa_func.count(cat_m.Product.id)).scalar() or 0
    active_count = db.query(sa_func.count(cat_m.Product.id)).filter(cat_m.Product.status == "active").scalar() or 0
    dead_stock = [
        {"product_id": p.id, "title": p.title, "stock": p.stock}
        for p in products.values()
        if p.stock > 0 and p.id not in {r["product_id"] for r in out}
    ]
    return {
        "window_days": days,
        "products": out,
        "catalog_total": catalog_count,
        "catalog_active": active_count,
        "never_sold_with_stock": dead_stock,
    }
