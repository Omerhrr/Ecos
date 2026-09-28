from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_perm
from app.logistics import models as m
from app.logistics import service
from app.orders import models as om

router = APIRouter(
    prefix="/shipments", tags=["logistics"],
    dependencies=[Depends(require_perm("logistics:read"))],
)


class TrackingEventIn(BaseModel):
    code: str
    description: str = ""
    location: str = ""


def serialize(db: Session, s: m.Shipment) -> dict:
    events = (
        db.query(m.TrackingEvent)
        .filter(m.TrackingEvent.shipment_id == s.id)
        .order_by(m.TrackingEvent.id)
        .all()
    )
    return {
        "id": s.id, "order_id": s.order_id, "status": s.status,
        "carrier": s.carrier, "tracking_code": s.tracking_code,
        "origin_country": s.origin_country, "destination_country": s.destination_country,
        "recipient_name": s.recipient_name, "recipient_phone": s.recipient_phone,
        "recipient_address": s.recipient_address, "weight_kg": s.weight_kg,
        "created_at": s.created_at.isoformat(),
        "delivered_at": s.delivered_at.isoformat() if s.delivered_at else None,
        "timeline": [
            {
                "id": e.id, "code": e.code, "description": e.description,
                "location": e.location, "occurred_at": e.occurred_at.isoformat(),
            }
            for e in events
        ],
    }


@router.get("")
def list_shipments(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(m.Shipment).order_by(m.Shipment.id.desc())
    if status:
        q = q.filter(m.Shipment.status == status)
    return [serialize(db, s) for s in q.all()]


@router.post("/create-for-order/{order_id}", status_code=201, dependencies=[Depends(require_perm("logistics:write"))])
def create_for_order(order_id: int, db: Session = Depends(get_db)):
    order = db.get(om.Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    try:
        shipment = service.create_shipment_for_order(db, order)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return serialize(db, shipment)


@router.get("/{shipment_id}")
def get_shipment(shipment_id: int, db: Session = Depends(get_db)):
    s = db.get(m.Shipment, shipment_id)
    if not s:
        raise HTTPException(404, "Shipment not found")
    return serialize(db, s)


@router.post("/{shipment_id}/events", dependencies=[Depends(require_perm("logistics:write"))])
def add_event(shipment_id: int, payload: TrackingEventIn, db: Session = Depends(get_db)):
    s = db.get(m.Shipment, shipment_id)
    if not s:
        raise HTTPException(404, "Shipment not found")
    try:
        service.add_tracking_event(
            db, s, code=payload.code, description=payload.description, location=payload.location
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return serialize(db, s)
