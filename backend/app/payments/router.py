from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.orders import models as om
from app.payments import models as m
from app.payments import service

router = APIRouter(prefix="/payments", tags=["payments"])


class CaptureIn(BaseModel):
    reference: str = ""


def serialize(p: m.Payment) -> dict:
    return {
        "id": p.id, "order_id": p.order_id, "method": p.method, "status": p.status,
        "amount": p.amount, "currency": p.currency, "provider": p.provider,
        "reference": p.reference, "reconciled": bool(p.reconciled),
        "collected_at": p.collected_at.isoformat() if p.collected_at else None,
        "created_at": p.created_at.isoformat(),
    }


@router.get("")
def list_payments(status: str | None = None, method: str | None = None, db: Session = Depends(get_db)):
    q = db.query(m.Payment).order_by(m.Payment.id.desc())
    if status:
        q = q.filter(m.Payment.status == status)
    if method:
        q = q.filter(m.Payment.method == method)
    return [serialize(p) for p in q.all()]


@router.get("/{payment_id}")
def get_payment(payment_id: int, db: Session = Depends(get_db)):
    p = db.get(m.Payment, payment_id)
    if not p:
        raise HTTPException(404, "Payment not found")
    return serialize(p)


@router.post("/{payment_id}/capture")
def capture(payment_id: int, payload: CaptureIn, db: Session = Depends(get_db)):
    """Capture a payment (gateway callback simulation, or manual COD collection)."""
    p = db.get(m.Payment, payment_id)
    if not p:
        raise HTTPException(404, "Payment not found")
    try:
        service.capture_payment(db, p, reference=payload.reference)
        service.sync_order_payment_status(db, p.order_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return serialize(p)
