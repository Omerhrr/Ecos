"""Returns / RMA API (plan §28)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_perm
from app.crm import models as crm_m
from app.orders import models as om
from app.returns import models as m
from app.returns import service

router = APIRouter(
    prefix="/returns", tags=["returns"],
    dependencies=[Depends(require_perm("returns:read"))],
)


class ReturnIn(BaseModel):
    order_id: int
    reason: str = "other"
    resolution: str = "refund"
    restock: bool = True
    notes: str = ""


class RejectIn(BaseModel):
    note: str = ""


def serialize(db: Session, r: m.ReturnOrder) -> dict:
    order = db.get(om.Order, r.order_id)
    customer = db.get(crm_m.Customer, r.customer_id)
    return {
        "id": r.id, "rma_number": r.rma_number, "order_id": r.order_id,
        "store_id": r.store_id, "customer_id": r.customer_id,
        "customer_name": customer.full_name if customer else None,
        "order_total": order.total if order else None,
        "order_status": order.status if order else None,
        "status": r.status, "reason": r.reason, "resolution": r.resolution,
        "restock": bool(r.restock), "refund_amount": r.refund_amount,
        "currency": r.currency, "notes": r.notes,
        "allowed_transitions": m.RETURN_TRANSITIONS.get(r.status, []),
        "created_at": r.created_at.isoformat(),
    }


@router.get("")
def list_returns(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(m.ReturnOrder).order_by(m.ReturnOrder.id.desc())
    if status:
        q = q.filter(m.ReturnOrder.status == status)
    return [serialize(db, r) for r in q.all()]


@router.get("/eligible-orders")
def eligible_orders(db: Session = Depends(get_db)):
    """Orders that can still enter the returns flow."""
    orders = (
        db.query(om.Order)
        .filter(om.Order.status.in_(m.RETURNABLE_ORDER_STATUSES))
        .order_by(om.Order.id.desc())
        .all()
    )
    open_order_ids = {
        r.order_id
        for r in db.query(m.ReturnOrder)
        .filter(m.ReturnOrder.status.in_(["requested", "approved", "received"]))
        .all()
    }
    out = []
    for o in orders:
        if o.id in open_order_ids:
            continue
        customer = db.get(crm_m.Customer, o.customer_id)
        out.append({
            "id": o.id, "status": o.status, "total": o.total,
            "currency": o.currency, "payment_status": o.payment_status,
            "customer_name": customer.full_name if customer else None,
        })
    return out


@router.post("", status_code=201, dependencies=[Depends(require_perm("returns:write"))])
def create_return(payload: ReturnIn, db: Session = Depends(get_db)):
    order = db.get(om.Order, payload.order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    try:
        rma = service.create_return(
            db, order=order, reason=payload.reason, resolution=payload.resolution,
            restock=payload.restock, notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return serialize(db, rma)


@router.get("/{rma_id}")
def get_return(rma_id: int, db: Session = Depends(get_db)):
    r = db.get(m.ReturnOrder, rma_id)
    if not r:
        raise HTTPException(404, "Return not found")
    return serialize(db, r)


@router.post("/{rma_id}/approve", dependencies=[Depends(require_perm("returns:write"))])
def approve(rma_id: int, db: Session = Depends(get_db)):
    r = db.get(m.ReturnOrder, rma_id)
    if not r:
        raise HTTPException(404, "Return not found")
    try:
        service.approve(db, r)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return serialize(db, r)


@router.post("/{rma_id}/reject", dependencies=[Depends(require_perm("returns:write"))])
def reject(rma_id: int, payload: RejectIn, db: Session = Depends(get_db)):
    r = db.get(m.ReturnOrder, rma_id)
    if not r:
        raise HTTPException(404, "Return not found")
    try:
        service.reject(db, r, note=payload.note)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return serialize(db, r)


@router.post("/{rma_id}/receive", dependencies=[Depends(require_perm("returns:write"))])
def receive(rma_id: int, warehouse_id: int | None = None, db: Session = Depends(get_db)):
    r = db.get(m.ReturnOrder, rma_id)
    if not r:
        raise HTTPException(404, "Return not found")
    try:
        service.mark_received(db, r, warehouse_id=warehouse_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return serialize(db, r)


@router.post("/{rma_id}/refund", dependencies=[Depends(require_perm("returns:write"))])
def refund(rma_id: int, db: Session = Depends(get_db)):
    r = db.get(m.ReturnOrder, rma_id)
    if not r:
        raise HTTPException(404, "Return not found")
    try:
        service.refund(db, r)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return serialize(db, r)


@router.post("/{rma_id}/close", dependencies=[Depends(require_perm("returns:write"))])
def close(rma_id: int, db: Session = Depends(get_db)):
    r = db.get(m.ReturnOrder, rma_id)
    if not r:
        raise HTTPException(404, "Return not found")
    try:
        service.close(db, r)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return serialize(db, r)
