"""Public storefront API (plan §14) — no authentication.

Everything here is customer-facing, so two hard rules apply:
1. Supplier identity and costs NEVER leak (plan §9) — products are exposed
   through `public_card()` only.
2. Only `active` products and `published` pages are ever returned.

Customer order intent is captured as CRM leads (plan §17): the storefront
is COD/agent-driven, so an order is created later by an operator, not by
the visitor directly.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.catalog import models as cm
from app.core.database import get_db
from app.core.events import publish
from app.core.pricing import price_product
from app.crm import models as crm_m
from app.landing_pages import models as lm
from app.landing_pages.blocks import resolve_blocks
from app.storefront import models as stm

public_router = APIRouter(prefix="/public", tags=["public-storefront"])


# ------------------------------------------------------------- serializers

def public_card(db: Session, p: cm.Product) -> dict:
    """Customer-safe product card. NO supplier, cost or margin fields."""
    breakdown = price_product(
        supplier_cost=p.supplier_cost, currency=p.currency,
        weight_kg=p.weight_kg, markup_pct=p.markup_pct,
    )
    images = p.images or []
    return {
        "id": p.id,
        "slug": p.slug,
        "title": p.title,
        "category": p.category,
        "brand": p.brand,
        "price_ngn": breakdown.ecos_price_ngn,
        "image": images[0] if images else None,
        "images": images,
        "in_stock": p.stock > 0,
    }


def _active_store(db: Session) -> stm.Store | None:
    return (
        db.query(stm.Store)
        .filter(stm.Store.status == "active")
        .order_by(stm.Store.id)
        .first()
    )


def store_dict(s: stm.Store) -> dict:
    return {
        "id": s.id, "name": s.name, "slug": s.slug,
        "country": s.country, "currency": s.currency,
    }


def page_dict(db: Session, page: lm.LandingPage) -> dict:
    return {
        "id": page.id,
        "slug": page.slug,
        "title": page.title,
        "blocks": resolve_blocks(db, page.blocks or []),
        "theme": page.theme or {},
        "seo": page.seo or {},
    }


# ----------------------------------------------------------------- routes

@public_router.get("/store")
def get_store(db: Session = Depends(get_db)):
    store = _active_store(db)
    return store_dict(store) if store else None


@public_router.get("/home")
def get_home(db: Session = Depends(get_db)):
    """Storefront home aggregate: store + published `home` page + latest products."""
    store = _active_store(db)
    if not store:
        raise HTTPException(404, "No active storefront yet")
    page = (
        db.query(lm.LandingPage)
        .filter(
            lm.LandingPage.org_id == store.org_id,
            lm.LandingPage.slug == "home",
            lm.LandingPage.status == "published",
        )
        .first()
    )
    products = (
        db.query(cm.Product)
        .filter(cm.Product.status == "active")
        .order_by(cm.Product.id.desc())
        .limit(8)
        .all()
    )
    return {
        "store": store_dict(store),
        "page": page_dict(db, page) if page else None,
        "products": [public_card(db, p) for p in products],
    }


@public_router.get("/products")
def list_public_products(category: str | None = None, db: Session = Depends(get_db)):
    q = db.query(cm.Product).filter(cm.Product.status == "active").order_by(cm.Product.id.desc())
    if category:
        q = q.filter(cm.Product.category == category)
    return [public_card(db, p) for p in q.limit(60).all()]


@public_router.get("/products/{slug}")
def get_public_product(slug: str, db: Session = Depends(get_db)):
    p = db.query(cm.Product).filter(cm.Product.slug == slug, cm.Product.status == "active").first()
    if not p:
        raise HTTPException(404, "Product not found")
    return {
        **public_card(db, p),
        "description": p.description,
        "specs": p.specs or {},
    }


@public_router.get("/pages/{slug}")
def get_public_page(slug: str, db: Session = Depends(get_db)):
    """Render a published landing page (the §15 engine's public face)."""
    page = db.query(lm.LandingPage).filter(
        lm.LandingPage.slug == slug, lm.LandingPage.status == "published"
    ).first()
    if not page:
        raise HTTPException(404, "Page not found")
    return page_dict(db, page)


class PublicLeadIn(BaseModel):
    product_slug: str
    contact_name: str = Field(min_length=2, max_length=255)
    contact_phone: str = Field(min_length=7, max_length=50)
    qty: int = Field(default=1, ge=1, le=99)
    note: str = ""


@public_router.post("/leads", status_code=201)
def submit_order_intent(payload: PublicLeadIn, db: Session = Depends(get_db)):
    """COD order intent from the storefront -> CRM lead (§14 -> §17)."""
    store = _active_store(db)
    if not store:
        raise HTTPException(404, "No active storefront yet")
    product = db.query(cm.Product).filter(
        cm.Product.slug == payload.product_slug, cm.Product.status == "active"
    ).first()
    if not product:
        raise HTTPException(404, "Product not found")

    lead = crm_m.Lead(
        store_id=store.id,
        product_id=product.id,
        contact_name=payload.contact_name.strip(),
        contact_phone=payload.contact_phone.strip(),
        status="new",
        source="storefront",
        campaign=f"storefront:/products/{product.slug}",
        notes=payload.note or "",
    )
    db.add(lead)
    db.flush()
    publish(db, "lead.created", {
        "lead_id": lead.id, "store_id": store.id, "product_id": product.id,
        "source": "storefront", "campaign": lead.campaign,
    })
    db.commit()
    return {
        "ok": True,
        "lead_id": lead.id,
        "message": "Order request received — an agent will call you to confirm. Pay on delivery.",
    }
