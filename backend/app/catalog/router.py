import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.catalog import models as m
from app.core.database import get_db
from app.core.deps import require_perm
from app.core.events import publish
from app.core.pricing import price_product
from app.supply import models as sm

router = APIRouter(
    prefix="/products", tags=["catalog"],
    dependencies=[Depends(require_perm("catalog:read"))],
)


class ProductIn(BaseModel):
    supplier_id: int
    title: str
    description: str = ""
    category: str = "general"
    brand: str = ""
    currency: str = "CNY"
    supplier_cost: float
    weight_kg: float = 0.5
    markup_pct: float | None = None
    stock: int = 0
    images: list[str] = []
    specs: dict = {}


class ProductPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    category: str | None = None
    supplier_cost: float | None = None
    weight_kg: float | None = None
    markup_pct: float | None = None
    status: str | None = None
    stock: int | None = None
    images: list[str] | None = None
    specs: dict | None = None


def _slugify(db: Session, title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "product"
    slug, n = base, 2
    while db.query(m.Product).filter(m.Product.slug == slug).first():
        slug = f"{base}-{n}"
        n += 1
    return slug


def serialize(db: Session, p: m.Product) -> dict:
    breakdown = price_product(
        supplier_cost=p.supplier_cost, currency=p.currency,
        weight_kg=p.weight_kg, markup_pct=p.markup_pct,
    )
    supplier = db.get(sm.Supplier, p.supplier_id)
    return {
        "id": p.id,
        "slug": p.slug,
        "supplier_id": p.supplier_id,
        "supplier_name": supplier.name if supplier else None,
        "supplier_lead_time_days": supplier.lead_time_days if supplier else None,
        # supplier identity stays internal to Luxeen (§9) — never surfaced to operator UIs
        "title": p.title, "description": p.description,
        "category": p.category, "brand": p.brand,
        "currency": p.currency, "supplier_cost": p.supplier_cost,
        "weight_kg": p.weight_kg, "markup_pct": p.markup_pct,
        "status": p.status, "stock": p.stock,
        "country_of_origin": p.country_of_origin,
        "images": p.images or [], "specs": p.specs or {},
        "created_at": p.created_at.isoformat(),
        "pricing": {
            "ecos_price_ngn": breakdown.ecos_price_ngn,
            "fx_rate": breakdown.fx_rate,
            "components": breakdown.components,
        },
    }


@router.get("")
def list_products(status: str | None = None, category: str | None = None, db: Session = Depends(get_db)):
    q = db.query(m.Product).order_by(m.Product.id.desc())
    if status:
        q = q.filter(m.Product.status == status)
    if category:
        q = q.filter(m.Product.category == category)
    return [serialize(db, p) for p in q.all()]


@router.post("", status_code=201, dependencies=[Depends(require_perm("catalog:write"))])
def create_product(payload: ProductIn, db: Session = Depends(get_db)):
    if not db.get(sm.Supplier, payload.supplier_id):
        raise HTTPException(400, "Unknown supplier")
    p = m.Product(**payload.model_dump())
    p.slug = _slugify(db, p.title)
    db.add(p)
    db.flush()
    publish(db, "product.created", {"product_id": p.id, "title": p.title, "supplier_id": p.supplier_id})
    db.commit()
    return serialize(db, p)


@router.get("/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db)):
    p = db.get(m.Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    return serialize(db, p)


@router.patch("/{product_id}", dependencies=[Depends(require_perm("catalog:write"))])
def patch_product(product_id: int, payload: ProductPatch, db: Session = Depends(get_db)):
    p = db.get(m.Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    changes = payload.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(p, k, v)
    publish(db, "product.updated", {"product_id": p.id, "changes": list(changes.keys())})
    if changes.get("status") == "active":
        publish(db, "product.published", {"product_id": p.id, "title": p.title})
    db.commit()
    return serialize(db, p)
