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

import json

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
from app.marketing import service as attribution
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
    # §16 attribution context captured by the storefront (sessionStorage last-touch)
    utm: dict = {}


# --------------------------------------------------------------------------
# §14 completion — public checkout: cart -> direct order (no auth)
# --------------------------------------------------------------------------

def _resolve_checkout_items(db: Session, items: list[dict]) -> list[dict]:
    resolved = []
    for item in items:
        slug = str(item.get("product_slug") or "").strip()
        qty = int(item.get("qty") or 0)
        if qty < 1:
            raise HTTPException(400, "Each item needs qty >= 1")
        product = db.query(cm.Product).filter(
            cm.Product.slug == slug, cm.Product.status == "active"
        ).first()
        if product is None:
            raise HTTPException(404, f"Product not found: {slug}")
        breakdown = price_product(
            supplier_cost=product.supplier_cost, currency=product.currency,
            weight_kg=product.weight_kg, markup_pct=product.markup_pct,
        )
        resolved.append({
            "product": product, "qty": qty,
            "unit_price": breakdown.ecos_price_ngn,
            "line_total": breakdown.ecos_price_ngn * qty,
        })
    if not resolved:
        raise HTTPException(400, "Cart is empty")
    return resolved


class CheckoutItemIn(BaseModel):
    product_slug: str
    qty: int = Field(ge=1, le=99)


class QuoteIn(BaseModel):
    items: list[CheckoutItemIn]
    delivery_fee: float = Field(default=0.0, ge=0)


@public_router.post("/checkout/quote")
def checkout_quote(payload: QuoteIn, db: Session = Depends(get_db)):
    """Price a cart (server-side waterfall) before placing the order."""
    lines = _resolve_checkout_items(db, [i.model_dump() for i in payload.items])
    items_total = sum(l["line_total"] for l in lines)
    return {
        "currency": "NGN",
        "lines": [
            {
                "product_slug": l["product"].slug,
                "title": l["product"].title,
                "qty": l["qty"],
                "unit_price": l["unit_price"],
                "line_total": l["line_total"],
                "in_stock": l["product"].stock >= l["qty"],
            }
            for l in lines
        ],
        "items_total": items_total,
        "delivery_fee": payload.delivery_fee,
        "total": items_total + payload.delivery_fee,
    }


class CheckoutIn(BaseModel):
    items: list[CheckoutItemIn]
    full_name: str = Field(min_length=2, max_length=255)
    contact_phone: str = Field(min_length=7, max_length=50)
    address: str = Field(min_length=4, max_length=1024)
    city: str = Field(max_length=100)
    state: str = Field(max_length=100)
    payment_method: str = "cod"  # cod | online_transfer
    note: str = ""
    utm: dict = {}


@public_router.post("/checkout", status_code=201)
def checkout(payload: CheckoutIn, db: Session = Depends(get_db)):
    """Cart -> direct order (§14 completion).

    Creates (or reuses, phone-matched) the customer, prices every line
    through the pricing engine, creates a real order + payment record, and
    notifies the operator org. COD stays the default corridor method.
    """
    from app.orders import service as order_service

    store = _active_store(db)
    if not store:
        raise HTTPException(404, "No active storefront yet")
    if payload.payment_method not in ("cod", "online_transfer"):
        raise HTTPException(400, "payment_method must be cod or online_transfer")

    lines = _resolve_checkout_items(db, [i.model_dump() for i in payload.items])
    for l in lines:
        if l["product"].stock < l["qty"]:
            raise HTTPException(
                409, f"Insufficient stock for {l['product'].title} — only "
                f"{l['product'].stock} left"
            )

    # find-or-create the customer by phone within this store (§18)
    phone = payload.contact_phone.strip()
    customer = (
        db.query(crm_m.Customer)
        .filter(crm_m.Customer.store_id == store.id, crm_m.Customer.phone == phone)
        .first()
    )
    if customer is None:
        customer = crm_m.Customer(
            store_id=store.id, full_name=payload.full_name.strip(),
            phone=phone, address=payload.address.strip(),
            city=payload.city.strip(), state=payload.state.strip(),
            country=store.country,
        )
        db.add(customer)
        db.flush()

    try:
        order = order_service.create_cart_order(
            db, store_id=store.id, customer_id=customer.id,
            items=[{"product_id": l["product"].id, "qty": l["qty"]} for l in lines],
            payment_method=payload.payment_method, delivery_fee=0.0,
            source="storefront_checkout",
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, str(exc))

    utm = attribution.normalize_utm(payload.utm)

    publish(db, "storefront.checkout_completed", {
        "order_id": order.id, "store_id": store.id, "customer_id": customer.id,
        "line_count": len(lines), "total_ngn": order.total,
        "payment_method": payload.payment_method, "utm": utm,
        "note": (payload.note or "")[:300],
    })
    db.commit()

    return {
        "ok": True,
        "order_id": order.id,
        "status": order.status,
        "total": order.total,
        "currency": "NGN",
        "payment_method": payload.payment_method,
        "customer_id": customer.id,
        "message": (
            "Order placed! Pay on delivery — our agent will call to confirm."
            if payload.payment_method == "cod"
            else "Order placed! Check your email for transfer instructions."
        ),
    }


@public_router.get("/orders/{order_id}")
def public_order_status(order_id: int, phone: str, db: Session = Depends(get_db)):
    """Customer order tracking — guarded by the checkout phone number.

    Returns the full customer-safe picture: status ladder, lines, payment,
    and (once fulfilled) the shipment with its §23 tracking checkpoints.
    """
    from app.logistics import models as lm
    from app.orders import models as om

    order = db.get(om.Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    customer = db.query(crm_m.Customer).filter(crm_m.Customer.id == order.customer_id).first()
    if not customer or customer.phone.strip() != phone.strip():
        raise HTTPException(403, "Phone does not match this order")
    items = db.query(om.OrderItem).filter(om.OrderItem.order_id == order.id).all()

    shipment = (
        db.query(lm.Shipment).filter(lm.Shipment.order_id == order.id).first()
    )
    shipment_out = None
    if shipment:
        checkpoints = (
            db.query(lm.TrackingEvent)
            .filter(lm.TrackingEvent.shipment_id == shipment.id)
            .order_by(lm.TrackingEvent.occurred_at.desc(), lm.TrackingEvent.id.desc())
            .limit(20)
            .all()
        )
        shipment_out = {
            "tracking_code": shipment.tracking_code,
            "carrier": shipment.carrier,
            "status": shipment.status,
            "created_at": shipment.created_at.isoformat() if shipment.created_at else None,
            "delivered_at": shipment.delivered_at.isoformat() if shipment.delivered_at else None,
            "tracking_events": [
                {
                    "code": e.code,
                    "description": e.description,
                    "location": e.location,
                    "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
                }
                for e in checkpoints
            ],
        }

    return {
        "order_id": order.id,
        "order_number": f"#{order.id}",
        "status": order.status,
        "payment_method": order.payment_method,
        "payment_status": order.payment_status,
        "total": order.total,
        "currency": order.currency,
        "placed_at": order.created_at.isoformat() if order.created_at else None,
        "items": [
            {"title": i.title, "qty": i.qty, "unit_price": i.unit_price}
            for i in items
        ],
        "shipment": shipment_out,
    }


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

    utm = attribution.normalize_utm(payload.utm)
    campaign_text = utm.get("utm_campaign", "")
    lead = crm_m.Lead(
        store_id=store.id,
        product_id=product.id,
        contact_name=payload.contact_name.strip(),
        contact_phone=payload.contact_phone.strip(),
        status="new",
        source="storefront",
        campaign=campaign_text or f"storefront:/products/{product.slug}",
        utm=json.dumps(utm),
        campaign_id=attribution.resolve_campaign_id(db, "storefront", campaign_text, utm),
        notes=payload.note or "",
    )
    db.add(lead)
    db.flush()
    publish(db, "lead.created", {
        "lead_id": lead.id, "store_id": store.id, "product_id": product.id,
        "source": "storefront", "campaign": lead.campaign, "campaign_id": lead.campaign_id,
        "utm": utm,
    })
    db.commit()
    return {
        "ok": True,
        "lead_id": lead.id,
        "message": "Order request received — an agent will call you to confirm. Pay on delivery.",
    }
