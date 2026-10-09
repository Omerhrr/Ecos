from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit import service as audit_service
from app.core.database import get_db
from app.core.deps import AuthContext, require_perm
from app.logistics import models as m
from app.logistics import rates as rates_service
from app.logistics import service
from app.orders import models as om

router = APIRouter(
    prefix="/shipments", tags=["logistics"],
    dependencies=[Depends(require_perm("logistics:read"))],
)

rates_router = APIRouter(
    prefix="/freight", tags=["logistics-rates"],
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


# ------------------------------------------------ §21 freight rate cards

class RateCardIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    mode: str = "air"
    origin_country: str = "CN"
    dest_country: str = "NG"
    org_id: int | None = None  # platform staff only; others scope to own org
    base_fixed_ngn: float = Field(default=0.0, ge=0)
    per_kg_ngn: float = Field(gt=0)
    fuel_surcharge_pct: float = Field(default=0.0, ge=0, le=1)
    customs_pct: float = Field(default=0.0, ge=0, le=1)
    min_charge_ngn: float = Field(default=0.0, ge=0)
    lead_time_days_min: int = Field(default=7, ge=0)
    lead_time_days_max: int = Field(default=14, ge=1)
    active: bool = True
    priority: int = 0


@rates_router.get("/cards")
def list_rate_cards(db: Session = Depends(get_db)):
    cards = db.query(m.FreightRateCard).order_by(
        m.FreightRateCard.mode, m.FreightRateCard.per_kg_ngn
    ).all()
    return {"cards": [rates_service.serialize_card(c) for c in cards],
            "modes": m.FREIGHT_MODES}


@rates_router.post("/cards", status_code=201, dependencies=[Depends(require_perm("logistics:write"))])
def create_rate_card(
    payload: RateCardIn, request: Request,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_perm("logistics:write")),
):
    if payload.mode not in m.FREIGHT_MODES:
        raise HTTPException(422, f"mode must be one of {m.FREIGHT_MODES}")
    if payload.lead_time_days_max < payload.lead_time_days_min:
        raise HTTPException(422, "lead_time_days_max must be >= min")
    c = m.FreightRateCard(
        org_id=payload_org(payload.org_id, ctx),
        name=payload.name.strip(),
        mode=payload.mode, origin_country=payload.origin_country.upper()[:2],
        dest_country=payload.dest_country.upper()[:2],
        base_fixed_ngn=payload.base_fixed_ngn, per_kg_ngn=payload.per_kg_ngn,
        fuel_surcharge_pct=payload.fuel_surcharge_pct, customs_pct=payload.customs_pct,
        min_charge_ngn=payload.min_charge_ngn,
        lead_time_days_min=payload.lead_time_days_min,
        lead_time_days_max=payload.lead_time_days_max,
        active=1 if payload.active else 0, priority=payload.priority,
    )
    db.add(c)
    db.flush()
    audit_service.record(
        db, ctx=ctx, request=request,
        action="logistics.rate_card_created", entity_type="freight_rate_card",
        entity_id=c.id, after=rates_service.serialize_card(c),
        auth_context="logistics:write",
    )
    db.commit()
    return rates_service.serialize_card(c)


@rates_router.patch("/cards/{card_id}", dependencies=[Depends(require_perm("logistics:write"))])
def patch_rate_card(
    card_id: int, payload: RateCardIn, request: Request,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_perm("logistics:write")),
):
    c = db.get(m.FreightRateCard, card_id)
    if not c:
        raise HTTPException(404, "Rate card not found")
    before = rates_service.serialize_card(c)
    data = payload.model_dump(exclude_none=True)
    for k, v in data.items():
        if k == "active":
            c.active = 1 if v else 0
        elif k in ("origin_country", "dest_country"):
            setattr(c, k, str(v).upper()[:2])
        else:
            setattr(c, k, v)
    audit_service.record(
        db, ctx=ctx, request=request,
        action="logistics.rate_card_updated", entity_type="freight_rate_card",
        entity_id=c.id, before=before, after=rates_service.serialize_card(c),
        auth_context="logistics:write",
    )
    db.commit()
    return rates_service.serialize_card(c)


def payload_org(requested: int | None, ctx: AuthContext) -> int | None:
    """Only platform staff may create platform-level (org NULL) config rows."""
    if ctx.is_platform:
        return requested
    return ctx.org.id if ctx.org else None
