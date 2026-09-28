from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.events import publish
from app.storefront import models as m

router = APIRouter(prefix="/stores", tags=["storefront"])


class StoreIn(BaseModel):
    org_id: int
    name: str
    slug: str
    country: str = "NG"
    currency: str = "NGN"


def serialize(s: m.Store) -> dict:
    return {
        "id": s.id, "org_id": s.org_id, "name": s.name, "slug": s.slug,
        "country": s.country, "currency": s.currency, "status": s.status,
        "created_at": s.created_at.isoformat(),
    }


@router.get("")
def list_stores(db: Session = Depends(get_db)):
    return [serialize(s) for s in db.query(m.Store).order_by(m.Store.id).all()]


@router.post("", status_code=201)
def create_store(payload: StoreIn, db: Session = Depends(get_db)):
    if db.query(m.Store).filter(m.Store.slug == payload.slug).first():
        raise HTTPException(400, "Slug already taken")
    s = m.Store(**payload.model_dump())
    db.add(s)
    db.flush()
    publish(db, "store.created", {"store_id": s.id, "name": s.name, "org_id": s.org_id})
    db.commit()
    return serialize(s)


@router.get("/{store_id}")
def get_store(store_id: int, db: Session = Depends(get_db)):
    s = db.get(m.Store, store_id)
    if not s:
        raise HTTPException(404, "Store not found")
    return serialize(s)
