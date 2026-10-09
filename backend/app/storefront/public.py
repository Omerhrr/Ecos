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
from app.finance import fx as fx_service
from app.landing_pages import models as lm
from app.landing_pages.blocks import resolve_blocks
from app.marketing import service as attribution
from app.storefront import models as stm

public_router = APIRouter(prefix="/public", tags=["public-storefront"])

DISPLAY_CURRENCIES = ["NGN", "USD"]


def _fx(db: Session, quote: str) -> dict:
    """Display-currency FX (§46). Falls back to the static corridor table."""
    quote = (quote or "NGN").upper()
    if quote not in DISPLAY_CURRENCIES:
        raise HTTPException(422, f"currency must be one of {DISPLAY_CURRENCIES}")
    if quote == "NGN":
        return {"rate": 1.0, "source": "identity"}
    try:
        rate, source = fx_service.get_rate(db, "NGN", quote)
    except ValueError:
        rate, source = 1530.0, "static-fallback"
    return {"rate": rate, "source": source}


def _money_ngn(amount: float, fx: dict) -> dict:
    """Customer-safe converted money block. Rounding: whole minor units."""
    return {
        "amount": round(amount * fx["rate"], 2),
        "rate": fx["rate"],
        "source": fx["source"],
    }


# ------------------------------------------------------------- serializers

def public_card(db: Session, p: cm.Product, fx: dict | None = None) -> dict:
    """Customer-safe product card. NO supplier, cost or margin fields."""
    breakdown = price_product(
        supplier_cost=p.supplier_cost, currency=p.currency,
        weight_kg=p.weight_kg, markup_pct=p.markup_pct,
    )
    images = p.images or []
    card = {
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
    if fx:
        card["price_display"] = _money_ngn(breakdown.ecos_price_ngn, fx)
    return card


def _public_variant(p: cm.Product, v, fx: dict | None = None) -> dict:
    """Customer-safe variant face (§10). SKU/cost stay internal (§9 spirit)."""
    adj = price_product(
        supplier_cost=p.supplier_cost + v.cost_delta, currency=p.currency,
        weight_kg=p.weight_kg + v.weight_delta_kg, markup_pct=p.markup_pct,
    )
    out = {
        "id": v.id,
        "label": f"{v.option_name}: {v.option_value}".strip(": ") if v.option_name else v.option_value,
        "price_ngn": adj.ecos_price_ngn,
        "stock": v.stock,
        "image": v.image,
        "in_stock": v.stock > 0,
    }
    if fx:
        out["price_display"] = _money_ngn(adj.ecos_price_ngn, fx)
    return out


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
def get_home(currency: str = "NGN", db: Session = Depends(get_db)):
    """Storefront home aggregate: store + published `home` page + latest products."""
    fx = _fx(db, currency)
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
        "currency": fx["rate"] and ("USD" if fx["rate"] != 1.0 else "NGN"),
        "fx": fx,
        "page": page_dict(db, page) if page else None,
        "products": [public_card(db, p, fx) for p in products],
    }


@public_router.get("/products")
def list_public_products(category: str | None = None, currency: str = "NGN", db: Session = Depends(get_db)):
    fx = _fx(db, currency)
    q = db.query(cm.Product).filter(cm.Product.status == "active").order_by(cm.Product.id.desc())
    if category:
        q = q.filter(cm.Product.category == category)
    return [public_card(db, p, fx) for p in q.limit(60).all()]


@public_router.get("/products/{slug}")
def get_public_product(slug: str, currency: str = "NGN", db: Session = Depends(get_db)):
    fx = _fx(db, currency)
    p = db.query(cm.Product).filter(cm.Product.slug == slug, cm.Product.status == "active").first()
    if not p:
        raise HTTPException(404, "Product not found")
    variants = (
        db.query(cm.ProductVariant)
        .filter(cm.ProductVariant.product_id == p.id, cm.ProductVariant.status == "active")
        .order_by(cm.ProductVariant.id)
        .all()
    )
    return {
        **public_card(db, p, fx),
        "description": p.description,
        "specs": p.specs or {},
        "videos": p.videos or [],
        "variants": [_public_variant(p, v, fx) for v in variants],
    }


# ---------------------------------------------------------------------- §46

@public_router.get("/fx")
def public_fx(quote: str = "USD", db: Session = Depends(get_db)):
    """Public display-FX (NGN -> quote) for the storefront currency toggle."""
    info = _fx(db, quote)
    return {"base": "NGN", **info}


@public_router.get("/pricing")
def public_pricing(db: Session = Depends(get_db)):
    """The USD pricing page (§46): every active product priced in NGN and USD.
    Supplier identity/costs stay hidden — the waterfall is applied, not shown."""
    try:
        usd_rate, usd_source = fx_service.get_rate(db, "NGN", "USD")
    except ValueError:
        usd_rate, usd_source = 1530.0, "static-fallback"
    fx_usd = {"rate": usd_rate, "source": usd_source}
    products = (
        db.query(cm.Product)
        .filter(cm.Product.status == "active")
        .order_by(cm.Product.id.desc())
        .all()
    )
    return {
        "base_currency": "NGN",
        "display_currencies": ["NGN", "USD"],
        "usd": {"rate": usd_rate, "source": usd_source},
        "products": [public_card(db, p, fx_usd) for p in products],
    }


def public_card_price(db: Session, p: cm.Product) -> float:
    return price_product(
        supplier_cost=p.supplier_cost, currency=p.currency,
        weight_kg=p.weight_kg, markup_pct=p.markup_pct,
    ).ecos_price_ngn


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

        variant = None
        variant_id = item.get("variant_id")
        if variant_id:
            variant = db.get(cm.ProductVariant, int(variant_id))
            if (variant is None or variant.product_id != product.id
                    or variant.status != "active"):
                raise HTTPException(400, f"Invalid option for {product.title}")
            if variant.stock < qty:
                raise HTTPException(
                    409, f"Insufficient stock for {variant.option_value or variant.sku} — "
                    f"only {variant.stock} left"
                )

        effective_cost = product.supplier_cost + (variant.cost_delta if variant else 0.0)
        effective_weight = product.weight_kg + (variant.weight_delta_kg if variant else 0.0)
        breakdown = price_product(
            supplier_cost=effective_cost, currency=product.currency,
            weight_kg=effective_weight, markup_pct=product.markup_pct,
        )
        label = None
        if variant is not None:
            label = (
                f"{variant.option_name}: {variant.option_value}"
                if variant.option_name else variant.option_value
            )
        resolved.append({
            "product": product, "variant": variant, "variant_label": label,
            "qty": qty, "unit_price": breakdown.ecos_price_ngn,
            "line_total": breakdown.ecos_price_ngn * qty,
        })
    if not resolved:
        raise HTTPException(400, "Cart is empty")
    return resolved


class CheckoutItemIn(BaseModel):
    product_slug: str
    qty: int = Field(ge=1, le=99)
    variant_id: int | None = None  # §10: the exact option the customer picked


class QuoteIn(BaseModel):
    items: list[CheckoutItemIn]
    delivery_fee: float = Field(default=0.0, ge=0)
    display_currency: str = "NGN"


@public_router.post("/checkout/quote")
def checkout_quote(payload: QuoteIn, db: Session = Depends(get_db)):
    """Price a cart (server-side waterfall) before placing the order."""
    lines = _resolve_checkout_items(db, [i.model_dump() for i in payload.items])
    items_total = sum(l["line_total"] for l in lines)
    total = items_total + payload.delivery_fee
    fx = _fx(db, payload.display_currency)
    out = {
        "currency": "NGN",
        "lines": [
            {
                "product_slug": l["product"].slug,
                "title": (
                    f"{l['product'].title} — {l['variant_label']}"
                    if l["variant_label"] else l["product"].title
                ),
                "qty": l["qty"],
                "unit_price": l["unit_price"],
                "line_total": l["line_total"],
                "in_stock": (
                    l["product"].stock >= l["qty"]
                    and (l["variant"] is None or l["variant"].stock >= l["qty"])
                ),
            }
            for l in lines
        ],
        "items_total": items_total,
        "delivery_fee": payload.delivery_fee,
        "total": total,
    }
    if fx["rate"] != 1.0:
        out["display"] = {
            "currency": payload.display_currency.upper(),
            "items_total": _money_ngn(items_total, fx),
            "total": _money_ngn(total, fx),
        }
    return out


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
    display_currency: str = "NGN"  # §46 display-only; settlement stays NGN


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
            items=[
                {
                    "product_id": l["product"].id, "qty": l["qty"],
                    "variant_id": (l["variant"].id if l["variant"] else None),
                }
                for l in lines
            ],
            payment_method=payload.payment_method, delivery_fee=0.0,
            source="storefront_checkout",
            display_currency=payload.display_currency,
            fx_rate_used=(_fx(db, payload.display_currency)["rate"]
                          if payload.display_currency.upper() != "NGN" else None),
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
        "display_currency": order.display_currency,
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
    else:
        # DROPSHIP (§20/§23): a supplier courier carries the parcel direct to
        # the customer — no Ecos shipment row exists, but the customer still
        # deserves a live timeline. Surface the corridor checkpoints from the
        # linked dropship sourcing orders. §9-safe by construction: tracking
        # facts only — no supplier identity, no economics, no buyer internals.
        shipment_out = _dropship_timeline(db, order)

    return {
        "order_id": order.id,
        "order_number": f"#{order.id}",
        "status": order.status,
        "payment_method": order.payment_method,
        "payment_status": order.payment_status,
        "total": order.total,
        "currency": order.currency,
        "display_currency": order.display_currency,
        "fx_rate_used": order.fx_rate_used,
        "placed_at": order.created_at.isoformat() if order.created_at else None,
        "items": [
            {"title": i.title, "qty": i.qty, "unit_price": i.unit_price}
            for i in items
        ],
        "shipment": shipment_out,
    }


def _scrub_supplier_text(text: str, names: list[str]) -> str:
    """Strip supplier-identifying free text off a public tracking line.

    Geography stays (city/country is the corridor's public story — the
    storefront advertises China→Nigeria shipping); what must never surface
    is the supplier as a BUSINESS: company names, emails, phone numbers.
    """
    import re

    out = text or ""
    for name in names:
        if name:
            out = re.sub(re.escape(name), "the origin facility", out, flags=re.IGNORECASE)
    out = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[contact]", out)          # emails
    # phone-like runs (>=10 digits — leaves dates like 2026-10-09 alone)
    out = re.sub(r"(?=(?:\D*\d){10})\+?\d[\d\s\-()]{8,}\d", "[contact]", out)
    return out


def _dropship_timeline(db: Session, order) -> dict | None:
    """Customer-safe tracking for a DROPSHIP-fulfilled order (§20, §23).

    The supplier ships direct to the recipient, so checkpoints live on the
    linked sourcing orders (`customer_order_id`), not on an Ecos shipment.
    This shapes them into the same payload the public page already renders.

    §9 isolation on a public surface: the payload carries the corridor
    ladder and nothing else — no supplier identity, no costs, no FX, no
    operator economics. `carrier` is intentionally generic.
    """
    from app.market import models as mm
    from app.supply import models as sm

    linked = (
        db.query(mm.SourcingOrder)
        .filter(
            mm.SourcingOrder.customer_order_id == order.id,
            mm.SourcingOrder.fulfillment_mode == "dropship",
            mm.SourcingOrder.status != "cancelled",
        )
        .all()
    )
    if not linked:
        return None

    # supplier company names, so free-text checkpoints can be scrubbed
    sup_names = [
        row[0]
        for row in db.query(sm.Supplier.name)
        .filter(sm.Supplier.id.in_([so.supplier_id for so in linked]))
        .all()
        if row[0]
    ]

    ladder = mm.DROPSHIP_STATUSES
    # least-advanced status wins — never tell the customer "delivered"
    # while one of their parcels is still clearing customs
    status = min((so.status for so in linked if so.status in ladder),
                 key=lambda s: ladder.index(s), default=linked[0].status)
    events = (
        db.query(mm.SourcingEvent)
        .filter(mm.SourcingEvent.sourcing_order_id.in_([so.id for so in linked]))
        .order_by(mm.SourcingEvent.occurred_at.desc(), mm.SourcingEvent.id.desc())
        .limit(30)
        .all()
    )
    all_delivered = all(so.status == "delivered" for so in linked)
    delivered_at = None
    if all_delivered and events:
        delivered_at = events[0].occurred_at.isoformat()
    codes = [so.order_number for so in linked]
    tracking_code = codes[0] if len(codes) == 1 else f"{codes[0]} +{len(codes) - 1} more"
    return {
        "tracking_code": tracking_code,
        "carrier": "Ecos Network — supplier direct mail",
        "status": status,
        "created_at": linked[0].created_at.isoformat() if linked[0].created_at else None,
        "delivered_at": delivered_at,
        "tracking_events": [
            {
                "code": e.code,
                "description": _scrub_supplier_text(e.description, sup_names),
                "location": _scrub_supplier_text(e.location, sup_names),
                "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
            }
            for e in events
        ],
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
