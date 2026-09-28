from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.catalog import models as cm
from app.core.database import get_db
from app.core.deps import require_perm
from app.core.events import publish
from app.crm import models as m
from app.orders import service as order_service
from app.storefront import models as stm

router = APIRouter(
    prefix="/leads", tags=["crm"],
    dependencies=[Depends(require_perm("crm:read"))],
)
customers_router = APIRouter(
    prefix="/customers", tags=["crm"],
    dependencies=[Depends(require_perm("crm:read"))],
)


class LeadIn(BaseModel):
    store_id: int
    product_id: int
    contact_name: str
    contact_phone: str
    source: str = "organic"
    campaign: str = ""
    assigned_agent: str = ""
    notes: str = ""


class LeadPatch(BaseModel):
    status: str | None = None
    assigned_agent: str | None = None
    notes: str | None = None


def serialize(db: Session, l: m.Lead) -> dict:
    product = db.get(cm.Product, l.product_id)
    store = db.get(stm.Store, l.store_id)
    return {
        "id": l.id, "store_id": l.store_id, "store_name": store.name if store else None,
        "product_id": l.product_id, "product_title": product.title if product else None,
        "customer_id": l.customer_id,
        "contact_name": l.contact_name, "contact_phone": l.contact_phone,
        "status": l.status, "source": l.source, "campaign": l.campaign,
        "assigned_agent": l.assigned_agent, "notes": l.notes,
        "created_at": l.created_at.isoformat(),
    }


@customers_router.get("")
def list_customers(store_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(m.Customer).order_by(m.Customer.id)
    if store_id:
        q = q.filter(m.Customer.store_id == store_id)
    return [
        {
            "id": c.id, "store_id": c.store_id, "full_name": c.full_name,
            "phone": c.phone, "city": c.city, "state": c.state, "country": c.country,
        }
        for c in q.all()
    ]


@router.get("")
def list_leads(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(m.Lead).order_by(m.Lead.id.desc())
    if status:
        q = q.filter(m.Lead.status == status)
    return [serialize(db, l) for l in q.all()]


@router.post("", status_code=201, dependencies=[Depends(require_perm("crm:write"))])
def create_lead(payload: LeadIn, db: Session = Depends(get_db)):
    if not db.get(cm.Product, payload.product_id):
        raise HTTPException(400, "Unknown product")
    if not db.get(stm.Store, payload.store_id):
        raise HTTPException(400, "Unknown store")
    lead = m.Lead(**payload.model_dump())
    db.add(lead)
    db.flush()
    publish(db, "lead.created", {
        "lead_id": lead.id, "store_id": lead.store_id,
        "product_id": lead.product_id, "source": lead.source, "campaign": lead.campaign,
    })
    db.commit()
    return serialize(db, lead)


@router.patch("/{lead_id}", dependencies=[Depends(require_perm("crm:write"))])
def patch_lead(lead_id: int, payload: LeadPatch, db: Session = Depends(get_db)):
    lead = db.get(m.Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    changes = payload.model_dump(exclude_none=True)
    if "status" in changes and changes["status"] not in m.LEAD_STATUSES:
        raise HTTPException(400, f"Invalid lead status: {changes['status']}")
    for k, v in changes.items():
        setattr(lead, k, v)
    publish(db, "lead.updated", {"lead_id": lead.id, "changes": list(changes.keys())})
    db.commit()
    return serialize(db, lead)


@router.post("/{lead_id}/convert", status_code=201, dependencies=[Depends(require_perm("crm:write"))])
def convert_lead(lead_id: int, qty: int = 1, db: Session = Depends(get_db)):
    """Convert a lead into a customer + order (pipeline: interested -> order_created)."""
    lead = db.get(m.Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    if lead.status in ("order_created", "confirmed", "fulfilled", "delivered"):
        raise HTTPException(400, f"Lead already converted (status={lead.status})")

    # Find-or-create the customer by phone within the store (§17 customer identity)
    customer = (
        db.query(m.Customer)
        .filter(m.Customer.store_id == lead.store_id, m.Customer.phone == lead.contact_phone)
        .first()
    )
    if not customer:
        customer = m.Customer(
            store_id=lead.store_id, full_name=lead.contact_name, phone=lead.contact_phone
        )
        db.add(customer)
        db.flush()

    order = order_service.create_order(
        db,
        store_id=lead.store_id,
        customer_id=customer.id,
        product_id=lead.product_id,
        qty=qty,
        payment_method="cod",
        lead_id=lead.id,
    )
    lead.customer_id = customer.id
    lead.status = "order_created"
    publish(db, "lead.updated", {"lead_id": lead.id, "changes": ["status", "customer_id"]})
    db.commit()
    return {"lead": serialize(db, lead), "order_id": order["id"]}
