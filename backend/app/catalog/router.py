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
    videos: list[str] = []  # §10: video media
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
    videos: list[str] | None = None
    specs: dict | None = None


class VariantIn(BaseModel):
    """§10: a buyable face of a product. Cost delta flows through the same
    §12 waterfall (margin stays derived from supplier truth)."""
    sku: str = ""                     # blank -> auto-generated
    option_name: str = ""
    option_value: str
    cost_delta: float = 0.0           # in product.currency
    weight_delta_kg: float = 0.0
    stock: int = 0
    image: str | None = None


class VariantPatch(BaseModel):
    sku: str | None = None
    option_name: str | None = None
    option_value: str | None = None
    cost_delta: float | None = None
    weight_delta_kg: float | None = None
    stock: int | None = None
    image: str | None = None
    status: str | None = None  # active | archived


def _slugify(db: Session, title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "product"
    slug, n = base, 2
    while db.query(m.Product).filter(m.Product.slug == slug).first():
        slug = f"{base}-{n}"
        n += 1
    return slug


def variant_price(db: Session, p: m.Product, v: m.ProductVariant) -> dict:
    """Variant face of the §12 waterfall: supplier cost + delta repriced."""
    base = price_product(
        supplier_cost=p.supplier_cost, currency=p.currency,
        weight_kg=p.weight_kg, markup_pct=p.markup_pct,
    )
    adj = price_product(
        supplier_cost=p.supplier_cost + v.cost_delta, currency=p.currency,
        weight_kg=p.weight_kg + v.weight_delta_kg, markup_pct=p.markup_pct,
    )
    return {
        "unit_price_ngn": adj.ecos_price_ngn,
        "delta_vs_base_ngn": round(adj.ecos_price_ngn - base.ecos_price_ngn, 2),
    }


def serialize_variant(db: Session, p: m.Product, v: m.ProductVariant) -> dict:
    pricing = variant_price(db, p, v)
    return {
        "id": v.id, "product_id": v.product_id, "sku": v.sku,
        "option_name": v.option_name, "option_value": v.option_value,
        "cost_delta": v.cost_delta, "weight_delta_kg": v.weight_delta_kg,
        "stock": v.stock, "image": v.image, "status": v.status,
        "label": f"{v.option_name}: {v.option_value}".strip(": ") if v.option_name else v.option_value,
        "unit_price_ngn": pricing["unit_price_ngn"],
        "delta_vs_base_ngn": pricing["delta_vs_base_ngn"],
    }


def _next_sku(db: Session, p: m.Product) -> str:
    n = db.query(m.ProductVariant).filter(m.ProductVariant.product_id == p.id).count() + 1
    base = f"P{p.id}"
    sku = f"{base}-{n:02d}"
    while db.query(m.ProductVariant).filter(m.ProductVariant.sku == sku).first():
        n += 1
        sku = f"{base}-{n:02d}"
    return sku


def serialize(db: Session, p: m.Product) -> dict:
    breakdown = price_product(
        supplier_cost=p.supplier_cost, currency=p.currency,
        weight_kg=p.weight_kg, markup_pct=p.markup_pct,
    )
    supplier = db.get(sm.Supplier, p.supplier_id)
    variants = (
        db.query(m.ProductVariant)
        .filter(m.ProductVariant.product_id == p.id, m.ProductVariant.status == "active")
        .order_by(m.ProductVariant.id)
        .all()
    )
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
        "images": p.images or [], "videos": p.videos or [], "specs": p.specs or {},
        "created_at": p.created_at.isoformat(),
        "pricing": {
            "ecos_price_ngn": breakdown.ecos_price_ngn,
            "fx_rate": breakdown.fx_rate,
            "components": breakdown.components,
        },
        "variants": [serialize_variant(db, p, v) for v in variants],
    }


@router.post("/{product_id}/variants", status_code=201,
             dependencies=[Depends(require_perm("catalog:write"))])
def create_variant(product_id: int, payload: VariantIn, db: Session = Depends(get_db)):
    p = db.get(m.Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    sku = payload.sku.strip() or _next_sku(db, p)
    if db.query(m.ProductVariant).filter(m.ProductVariant.sku == sku).first():
        raise HTTPException(400, f"SKU already exists: {sku}")
    v = m.ProductVariant(
        product_id=p.id, sku=sku,
        option_name=payload.option_name.strip(), option_value=payload.option_value.strip(),
        cost_delta=payload.cost_delta, weight_delta_kg=payload.weight_delta_kg,
        stock=payload.stock, image=payload.image,
    )
    db.add(v)
    db.flush()
    publish(db, "product.variant_created", {
        "product_id": p.id, "variant_id": v.id, "sku": v.sku,
        "option": f"{v.option_name}:{v.option_value}",
    })
    db.commit()
    return serialize_variant(db, p, v)


@router.get("/{product_id}/variants")
def list_variants(product_id: int, include_archived: bool = False, db: Session = Depends(get_db)):
    p = db.get(m.Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    q = db.query(m.ProductVariant).filter(m.ProductVariant.product_id == p.id)
    if not include_archived:
        q = q.filter(m.ProductVariant.status == "active")
    return [serialize_variant(db, p, v) for v in q.order_by(m.ProductVariant.id).all()]


@router.patch("/variants/{variant_id}", dependencies=[Depends(require_perm("catalog:write"))])
def patch_variant(variant_id: int, payload: VariantPatch, db: Session = Depends(get_db)):
    v = db.get(m.ProductVariant, variant_id)
    if not v:
        raise HTTPException(404, "Variant not found")
    p = db.get(m.Product, v.product_id)
    changes = payload.model_dump(exclude_none=True)
    if "sku" in changes:
        sku = changes["sku"].strip()
        existing = db.query(m.ProductVariant).filter(m.ProductVariant.sku == sku).first()
        if existing and existing.id != v.id:
            raise HTTPException(400, f"SKU already exists: {sku}")
        if not sku:
            changes.pop("sku")
        else:
            changes["sku"] = sku
    for k, val in changes.items():
        setattr(v, k, val)
    publish(db, "product.variant_updated", {"product_id": v.product_id, "variant_id": v.id, "changes": list(changes.keys())})
    db.commit()
    return serialize_variant(db, p, v)


@router.delete("/variants/{variant_id}", status_code=204,
               dependencies=[Depends(require_perm("catalog:write"))])
def archive_variant(variant_id: int, db: Session = Depends(get_db)):
    """Variants referenced by order history are archived, never hard-deleted."""
    v = db.get(m.ProductVariant, variant_id)
    if not v:
        raise HTTPException(404, "Variant not found")
    v.status = "archived"
    publish(db, "product.variant_archived", {"product_id": v.product_id, "variant_id": v.id})
    db.commit()
    return None


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
