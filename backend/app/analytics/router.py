"""Analytics across the commerce lifecycle (plan §29).

Phase 1 exposes business, product, and funnel aggregates computed directly
from the domain tables. As volume grows these move to a warehouse / the
network intelligence layer (§48).
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.crm import models as cm
from app.orders import models as om
from app.payments import models as pm

router = APIRouter(prefix="/analytics", tags=["analytics"])


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
