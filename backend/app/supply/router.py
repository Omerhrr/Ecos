from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_perm
from app.core.events import publish
from app.market import models as mm
from app.supply import models as m

router = APIRouter(
    prefix="/suppliers", tags=["supply"],
    dependencies=[Depends(require_perm("supply:read"))],
)


class SupplierIn(BaseModel):
    name: str
    country: str = "CN"
    city: str = ""
    lead_time_days: int = 14
    notes: str = ""


class SupplierPatch(BaseModel):
    status: str | None = None
    rating: float | None = None
    lead_time_days: int | None = None
    notes: str | None = None


def serialize(s: m.Supplier) -> dict:
    return {
        "id": s.id, "name": s.name, "country": s.country, "city": s.city,
        "status": s.status, "rating": s.rating, "lead_time_days": s.lead_time_days,
        "notes": s.notes, "created_at": s.created_at.isoformat(),
    }


@router.get("")
def list_suppliers(db: Session = Depends(get_db)):
    return [serialize(s) for s in db.query(m.Supplier).order_by(m.Supplier.id).all()]


@router.post("", status_code=201, dependencies=[Depends(require_perm("supply:write"))])
def create_supplier(payload: SupplierIn, db: Session = Depends(get_db)):
    s = m.Supplier(**payload.model_dump())
    db.add(s)
    db.flush()
    publish(db, "supplier.created", {"supplier_id": s.id, "name": s.name})
    db.commit()
    return serialize(s)


@router.patch("/{supplier_id}", dependencies=[Depends(require_perm("supply:write"))])
def patch_supplier(supplier_id: int, payload: SupplierPatch, db: Session = Depends(get_db)):
    s = db.get(m.Supplier, supplier_id)
    if not s:
        raise HTTPException(404, "Supplier not found")
    changes = payload.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(s, k, v)
    publish(db, "supplier.updated", {"supplier_id": s.id, "changes": list(changes.keys())})
    db.commit()
    return serialize(s)


@router.get("/performance/summary")
def supplier_performance(db: Session = Depends(get_db)):
    """§8 supplier performance — derived from the live corridor data.

    Per supplier: listing pipeline, sourcing volumes, accept rate, fulfilment
    speed (accept -> ship), ladder completion (share of orders that arrived),
    cancellations and units sourced. No new state: everything is derived so
    the numbers stay honest as the corridor runs.
    """
    suppliers = db.query(m.Supplier).order_by(m.Supplier.id).all()
    out = []
    for s in suppliers:
        listings = db.query(mm.SupplierProduct).filter(
            mm.SupplierProduct.supplier_id == s.id
        ).all()
        by_status: dict[str, int] = {}
        for l in listings:
            by_status[l.status] = by_status.get(l.status, 0) + 1

        orders = db.query(mm.SourcingOrder).filter(
            mm.SourcingOrder.supplier_id == s.id
        ).all()
        total = len(orders)
        cancelled = sum(1 for o in orders if o.status == "cancelled")
        active = [o for o in orders if o.status not in ("cancelled",)]
        # accept = the order left pending_payment and the supplier took it on
        accepted = [o for o in active if o.status != "pending_payment"]
        received = [o for o in active if o.status == "received"]
        arrived = [o for o in active if o.status in ("arrived", "received")]
        units = sum(o.qty for o in received)

        # fulfilment speed: paid -> first ladder movement beyond paid
        accept_hours: list[float] = []
        transit_days: list[float] = []
        for o in orders:
            if not o.paid_at:
                continue
            events = (
                db.query(mm.SourcingEvent)
                .filter(mm.SourcingEvent.sourcing_order_id == o.id)
                .order_by(mm.SourcingEvent.id)
                .all()
            )
            first_move = next(
                (e for e in events if e.code not in ("supplier_processing",)), None
            )
            if first_move and first_move.occurred_at and o.paid_at:
                accept_hours.append(
                    (first_move.occurred_at - o.paid_at).total_seconds() / 3600
                )
            arrival = next(
                (e for e in events if e.code == "delivered"), None
            )
            if arrival and arrival.occurred_at and o.paid_at:
                transit_days.append(
                    (arrival.occurred_at - o.paid_at).total_seconds() / 86400
                )

        def _avg(values: list[float], nd: int = 1) -> float | None:
            return round(sum(values) / len(values), nd) if values else None

        out.append({
            "supplier_id": s.id, "name": s.name, "city": s.city, "country": s.country,
            "status": s.status,
            "listings": {"total": len(listings), "by_status": by_status,
                         "published": by_status.get("published", 0)},
            "sourcing": {
                "orders_total": total,
                "cancelled": cancelled,
                "cancel_rate": round(cancelled / total, 2) if total else None,
                "accept_rate": round(len(accepted) / len(active), 2) if active else None,
                "avg_accept_hours": _avg(accept_hours),
                "avg_transit_days": _avg(transit_days),
                "arrival_rate": round(len(arrived) / len(active), 2) if active else None,
                "received_orders": len(received),
                "units_received": units,
            },
            "last_activity": max(
                (o.updated_at or o.created_at for o in orders), default=None
            ).isoformat() if orders else None,
        })
    return {"suppliers": out}
