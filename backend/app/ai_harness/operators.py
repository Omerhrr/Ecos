"""Built-in AI operator blueprints (plan §31-34).

Each blueprint is a narrow, auditable role:

    gather()  reads live Ecos state and packs it into the prompt context —
              plus a deterministic `[[HEURISTIC]]` payload the fallback
              engine uses when no DeepSeek key is configured.
    apply()   the governed side effect executed ONLY after a human approves
              the run's proposal (§37-38). Advisory blueprints never mutate.

The harness (service.py) owns the run loop; blueprints stay pure.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.catalog import models as cm
from app.core import events
from app.core.pricing import FX_RATES, LOGISTICS_NGN_PER_KG, PAYMENT_COST_PCT, LUXEEN_MARGIN_PCT, price_product
from app.crm import models as crm_m
from app.landing_pages import models as lpm
from app.orders import models as om
from app.supply import models as sm

GatherFn = Callable[[Session, dict], dict[str, Any]]
ApplyFn = Callable[[Session, Any, dict, dict], dict[str, Any]]


def _sales_snapshot(db: Session) -> dict[int, dict]:
    """units + revenue per product across non-cancelled orders."""
    rows = (
        db.query(
            om.OrderItem.product_id,
            sa_func.sum(om.OrderItem.qty).label("units"),
            sa_func.sum(om.OrderItem.qty * om.OrderItem.unit_price).label("revenue"),
        )
        .join(om.Order, om.Order.id == om.OrderItem.order_id)
        .filter(om.Order.status.notin_(["draft", "cancelled", "failed"]))
        .group_by(om.OrderItem.product_id)
        .all()
    )
    return {r.product_id: {"units": int(r.units or 0), "revenue": float(r.revenue or 0.0)} for r in rows}


def _unique_page_slug(db: Session, base: str) -> str:
    base = re.sub(r"[^a-z0-9-]+", "-", base.lower()).strip("-") or "ai-page"
    slug, n = base, 2
    while db.query(lpm.LandingPage).filter(lpm.LandingPage.slug == slug).count():
        slug = f"{base}-ai-{n}"
        n += 1
    return slug


# --------------------------------------------------------------------------
# 1. Pricing analyst — "Margin Sentinel" (§33 pricing domain support)
# --------------------------------------------------------------------------

def _gather_pricing(db: Session, params: dict) -> dict[str, Any]:
    sales = _sales_snapshot(db)
    products = db.query(cm.Product).filter(cm.Product.status == "active").all()
    recs = []
    for p in products:
        s = sales.get(p.id, {"units": 0, "revenue": 0.0})
        b = price_product(p.supplier_cost, "CNY", p.weight_kg, p.markup_pct)
        current = b.ecos_price_ngn
        if s["units"] == 0 and p.stock > 50:
            factor, why = 0.92, "no sales yet with healthy stock — stimulate demand"
        elif s["units"] >= 10:
            factor, why = 1.06, "demand is proven (10+ units) — capture more margin"
        else:
            factor, why = 1.0, "early signal — hold price and observe"
        suggested = round(current * factor / 5) * 5
        cost = b.supplier_cost_ngn
        base = cost + b.logistics_ngn + b.payment_cost_ngn + b.luxeen_margin_ngn
        markup = (suggested - base) / cost if cost else p.markup_pct
        recs.append({
            "product_id": p.id, "product_title": p.title,
            "current_price_ngn": current, "suggested_price_ngn": suggested,
            "units_sold": s["units"], "stock": p.stock,
            "margin_pct_current": round((current - base) / current * 100, 1) if current else 0,
            "rationale": why,
        })
        # stash the inverse-computed markup for apply()
        recs[-1]["_markup_pct"] = round(markup, 4)
    return {"products": recs}


def _heuristic_pricing(gathered: dict[str, Any]) -> dict[str, Any]:
    recs = [{k: v for k, v in r.items() if not k.startswith("_")} for r in gathered["products"]]
    changes = [r for r in recs if r["suggested_price_ngn"] != r["current_price_ngn"]]
    return {
        "analysis": "Margin + velocity scan across the active catalog.",
        "recommendations": recs,
        "summary": (
            f"{len(changes)} of {len(recs)} products merit a price move; "
            f"{len(recs) - len(changes)} hold steady."
        ),
    }


def _apply_pricing(db: Session, operator, output: dict, actor: dict) -> dict[str, Any]:
    applied = []
    for r in output.get("recommendations", []):
        p = db.get(cm.Product, r.get("product_id"))
        suggested = r.get("suggested_price_ngn")
        if p and suggested:
            # recompute the markup that hits the approved price against
            # CURRENT costs (they may have drifted since the run)
            b = price_product(p.supplier_cost, "CNY", p.weight_kg, p.markup_pct)
            if b.ecos_price_ngn == suggested:
                continue  # no move proposed for this product
            base = (b.supplier_cost_ngn + b.logistics_ngn
                    + b.payment_cost_ngn + b.luxeen_margin_ngn)
            if b.supplier_cost_ngn:
                p.markup_pct = round((suggested - base) / b.supplier_cost_ngn, 4)
                applied.append({"product_id": p.id, "old_price_ngn": b.ecos_price_ngn,
                                "new_price_ngn": suggested})
    return {"applied_changes": applied}


# --------------------------------------------------------------------------
# 2. Demand forecaster — "Stock Prophet" (advisory, §33)
# --------------------------------------------------------------------------

def _gather_demand(db: Session, params: dict) -> dict[str, Any]:
    sales = _sales_snapshot(db)
    products = db.query(cm.Product).filter(cm.Product.status == "active").all()
    out = []
    for p in products:
        supplier = db.get(sm.Supplier, p.supplier_id)
        lead_weeks = max(1.0, (supplier.lead_time_days if supplier else 14) / 7.0)
        units = sales.get(p.id, {"units": 0, "revenue": 0.0})["units"]
        velocity = round(units / 4.0, 1)  # 4-week observed window
        cover = round(p.stock / velocity, 1) if velocity else None
        reorder = 0
        if velocity:
            need = lead_weeks * velocity * 1.5  # 1.5x safety stock
            reorder = max(0, int(round(need - p.stock)))
        out.append({
            "product_id": p.id, "product_title": p.title,
            "units_sold_4w": units, "weekly_velocity": velocity,
            "weeks_of_cover": cover, "supplier_lead_time_weeks": round(lead_weeks, 1),
            "stock": p.stock, "suggested_reorder_qty": reorder,
            "risk": ("stockout" if cover is not None and cover < lead_weeks
                     else "healthy" if cover is None or cover > 6 else "watch"),
        })
    return {"products": out}


def _heuristic_demand(gathered: dict[str, Any]) -> dict[str, Any]:
    prods = gathered["products"]
    risky = [p for p in prods if p["risk"] == "stockout"]
    return {
        "forecast_window": "4-week trailing velocity, 1.5x safety stock",
        "products": prods,
        "summary": (
            f"{len(risky)} product(s) risk stockout before supplier lead time "
            f"covers reorder; {sum(p['suggested_reorder_qty'] for p in prods)} units total reorder proposal."
        ),
    }


# --------------------------------------------------------------------------
# 3. Copywriter — "Launch Scribe" (§15 landing page engine support)
# --------------------------------------------------------------------------

def _gather_copy(db: Session, params: dict) -> dict[str, Any]:
    p = db.get(cm.Product, int(params.get("product_id", 0)))
    if p is None:
        raise ValueError("product_id not found")
    b = price_product(p.supplier_cost, "CNY", p.weight_kg, p.markup_pct)
    return {"product": {
        "id": p.id, "title": p.title, "category": p.category, "slug": p.slug,
        "price_ngn": b.ecos_price_ngn, "description": p.description,
        "specs": p.specs, "stock": p.stock,
    }}


def _heuristic_copy(gathered: dict[str, Any]) -> dict[str, Any]:
    p = gathered["product"]
    return {
        "headline": f"{p['title']} — delivered to your door",
        "subheadline": (
            f"Quality-tested {p['category'].replace('-', ' ')} from our China network. "
            f"₦{p['price_ngn']:,.0f} — pay cash on delivery."
        ),
        "cta_label": "Order now", "cta_href": f"/products/{p['slug']}",
        "bullets": [
            "Pay on delivery — zero risk",
            "7-14 day tracked China→Nigeria delivery",
            "7-day returns, no questions asked",
        ],
        "rationale": "Highlights COD trust signals + delivery window; proven converter in this corridor.",
    }


def _apply_copy(db: Session, operator, output: dict, actor: dict) -> dict[str, Any]:
    product = db.get(cm.Product, output.get("_product_id", 0))
    if product is None:
        raise ValueError("proposal product no longer exists")
    blocks = [
        {"id": "b1", "type": "hero", "headline": output.get("headline", product.title),
         "subheadline": output.get("subheadline", ""),
         "cta_label": output.get("cta_label", "Order now"),
         "cta_href": f"/products/{product.slug}",
         "image": product.images[0] if product.images else f"https://picsum.photos/seed/{product.slug}/1600/900"},
        {"id": "b2", "type": "trust_badges",
         "items": "💵 | Pay on delivery\n🚚 | Tracked door-to-door\n✅ | 7-day returns"},
        {"id": "b3", "type": "product_showcase", "title": "More from the store", "mode": "latest", "limit": "3"},
    ]
    page = lpm.LandingPage(
        org_id=operator.org_id,
        slug=_unique_page_slug(db, f"{product.slug or product.id}-ai-copy"),
        title=f"{product.title} — AI campaign page",
        status="draft", blocks=blocks, theme={"primary": "#0ea5e9"},
        seo={"title": output.get("headline", product.title),
             "description": output.get("subheadline", "")[:160]},
        created_by=actor.get("user_id"),
    )
    db.add(page)
    db.flush()
    return {"landing_page_id": page.id, "slug": page.slug, "status": "draft (publish from Landing Pages)"}


# --------------------------------------------------------------------------
# 4. Lead responder — "Lead Whisperer" (§17 CRM support)
# --------------------------------------------------------------------------

def _gather_lead(db: Session, params: dict) -> dict[str, Any]:
    lead = db.get(crm_m.Lead, int(params.get("lead_id", 0)))
    if lead is None:
        raise ValueError("lead_id not found")
    product = db.get(cm.Product, lead.product_id) if lead.product_id else None
    return {"lead": {
        "id": lead.id, "contact_name": lead.contact_name, "status": lead.status,
        "source": lead.source, "campaign": lead.campaign,
        "product": product.title if product else None,
        "notes": lead.notes,
    }}


def _heuristic_lead(gathered: dict[str, Any]) -> dict[str, Any]:
    lead = gathered["lead"]
    first = lead["contact_name"].split()[0] if lead["contact_name"] else "there"
    product = lead.get("product") or "the item you asked about"
    return {
        "draft_reply": (
            f"Hi {first}! Thanks for your interest in the {product}. "
            "It is in stock and ships from our China hub with door-to-door tracking — "
            "you only pay when it arrives. Would today or tomorrow work for a quick confirmation call?"
        ),
        "next_action": "Call to confirm order, then convert the lead in CRM",
        "tone": "warm, concise, COD trust-forward",
    }


def _apply_lead(db: Session, operator, output: dict, actor: dict) -> dict[str, Any]:
    lead = db.get(crm_m.Lead, output.get("_lead_id", 0))
    if lead is None:
        raise ValueError("proposal lead no longer exists")
    reply = output.get("draft_reply", "")
    lead.notes = ((lead.notes + "\n" if lead.notes else "") + f"[AI draft] {reply}").strip()
    changed = ["notes"]
    if lead.status == "new":
        lead.status = "contacted"
        changed.append("status")
    events.publish(db, "lead.updated", {"lead_id": lead.id, "changes": changed})
    return {"lead_id": lead.id, "updated": changed, "draft_saved": True}


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

BLUEPRINTS: dict[str, dict[str, Any]] = {
    "pricing_analyst": {
        "code": "pricing_analyst",
        "name": "Margin Sentinel",
        "role_description": "Scans catalog margins vs. sales velocity and proposes price moves.",
        "advisory": False,
        "input_fields": [],
        "gather": _gather_pricing,
        "heuristic": _heuristic_pricing,
        "apply": _apply_pricing,
        "task_brief": (
            "You are Margin Sentinel, a pricing analyst for a China→Nigeria e-commerce "
            "corridor. Using the catalog snapshot, propose 0-5 price adjustments. "
            "Respond ONLY with JSON: {\"analysis\": str, \"recommendations\": "
            "[{\"product_id\": int, \"suggested_price_ngn\": number, \"rationale\": str}], \"summary\": str}"
        ),
    },
    "demand_forecaster": {
        "code": "demand_forecaster",
        "name": "Stock Prophet",
        "role_description": "Forecasts restock needs from sales velocity vs. supplier lead times. Advisory only.",
        "advisory": True,
        "input_fields": [],
        "gather": _gather_demand,
        "heuristic": _heuristic_demand,
        "apply": None,
        "task_brief": (
            "You are Stock Prophet, a demand planner. Using the velocity snapshot, flag "
            "stockout risk and propose reorder quantities. Respond ONLY with JSON: "
            "{\"summary\": str, \"products\": [{\"product_id\": int, \"risk\": str, "
            "\"suggested_reorder_qty\": int, \"rationale\": str}]}"
        ),
    },
    "copywriter": {
        "code": "copywriter",
        "name": "Launch Scribe",
        "role_description": "Writes campaign landing-page copy for a product; approval publishes a draft page.",
        "advisory": False,
        "input_fields": [{"key": "product_id", "label": "Product", "type": "number", "required": True}],
        "gather": _gather_copy,
        "heuristic": _heuristic_copy,
        "apply": _apply_copy,
        "task_brief": (
            "You are Launch Scribe, a direct-response copywriter for COD e-commerce in Nigeria. "
            "Write landing hero copy for the given product. Respond ONLY with JSON: "
            "{\"headline\": str, \"subheadline\": str, \"cta_label\": str, \"bullets\": [str], "
            "\"rationale\": str}"
        ),
    },
    "lead_responder": {
        "code": "lead_responder",
        "name": "Lead Whisperer",
        "role_description": "Drafts a personal follow-up reply for a CRM lead; approval saves it to the lead.",
        "advisory": False,
        "input_fields": [{"key": "lead_id", "label": "Lead", "type": "number", "required": True}],
        "gather": _gather_lead,
        "heuristic": _heuristic_lead,
        "apply": _apply_lead,
        "task_brief": (
            "You are Lead Whisperer, a sales assistant for COD e-commerce. Draft a short "
            "follow-up reply for the given lead. Respond ONLY with JSON: "
            "{\"draft_reply\": str, \"next_action\": str, \"tone\": str}"
        ),
    },
}
