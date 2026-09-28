from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.events import publish
from app.supply import models as m

router = APIRouter(prefix="/suppliers", tags=["supply"])


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


@router.post("", status_code=201)
def create_supplier(payload: SupplierIn, db: Session = Depends(get_db)):
    s = m.Supplier(**payload.model_dump())
    db.add(s)
    db.flush()
    publish(db, "supplier.created", {"supplier_id": s.id, "name": s.name})
    db.commit()
    return serialize(s)


@router.patch("/{supplier_id}")
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
