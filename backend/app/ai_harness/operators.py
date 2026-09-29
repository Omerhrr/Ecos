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
from datetime import datetime, timezone
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
# 5. Product research — "Market Scout" (§32, advisory)
# --------------------------------------------------------------------------

def _gather_research(db: Session, params: dict) -> dict[str, Any]:
    sales = _sales_snapshot(db)
    products = db.query(cm.Product).filter(cm.Product.status == "active").all()
    rows = []
    categories: dict[str, dict] = {}
    for p in products:
        s = sales.get(p.id, {"units": 0, "revenue": 0.0})
        b = price_product(p.supplier_cost, p.currency, p.weight_kg, p.markup_pct)
        velocity = round(s["units"] / 4.0, 2)
        supplier = db.get(sm.Supplier, p.supplier_id)
        rows.append({
            "product_id": p.id, "title": p.title, "category": p.category,
            "units_sold_4w": s["units"], "revenue_ngn": s["revenue"],
            "weekly_velocity": velocity, "stock": p.stock,
            "price_ngn": b.ecos_price_ngn,
            "margin_per_unit_ngn": round(b.operator_margin_ngn, 2),
            "supplier_rating": supplier.rating if supplier else None,
        })
        cat = categories.setdefault(p.category, {"products": 0, "units": 0, "revenue_ngn": 0.0})
        cat["products"] += 1
        cat["units"] += s["units"]
        cat["revenue_ngn"] = round(cat["revenue_ngn"] + s["revenue"], 2)
    rows.sort(key=lambda r: (-r["weekly_velocity"], -r["margin_per_unit_ngn"]))
    return {"products": rows, "category_summary": categories}


def _heuristic_research(gathered: dict[str, Any]) -> dict[str, Any]:
    prods = gathered["products"]
    winners = [
        {"product_id": p["product_id"], "title": p["title"], "signal": "proven_demand_thin_stock",
         "action": "scale ad spend + reorder now",
         "rationale": f"{p['units_sold_4w']} units in 4w with only {p['stock']} left — demand outruns supply."}
        for p in prods if p["weekly_velocity"] >= 2 and p["stock"] < 25
    ]
    sleepers = [
        {"product_id": p["product_id"], "title": p["title"], "signal": "healthy_margin_no_traction",
         "action": "test a dedicated landing page + 5-7 day promo",
         "rationale": f"Margin ₦{p['margin_per_unit_ngn']:,.0f}/unit but {p['units_sold_4w']} sales — the offer needs traffic, not price."}
        for p in prods if p["weekly_velocity"] < 2 and p["margin_per_unit_ngn"] >= 2000 and p["stock"] > 30
    ]
    cats = gathered["category_summary"]
    deep = sorted(cats.items(), key=lambda kv: -kv[1]["revenue_ngn"])[:2]
    gaps = [
        {"category": name, "signal": "revenue_concentration",
         "action": f"Source 2-3 more {name.replace('-', ' ')} SKUs from the supplier network",
         "rationale": f"{data['products']} SKU(s) already drive ₦{data['revenue_ngn']:,.0f} — widen the assortment while it's hot."}
        for name, data in deep
    ]
    return {
        "opportunities": {"scale_now": winners, "revive": sleepers, "category_gaps": gaps},
        "summary": (
            f"{len(winners)} scale-now, {len(sleepers)} revive, {len(gaps)} category gap(s) "
            f"across {len(prods)} active SKUs."
        ),
        "rationale": "Ranked by 4-week velocity, unit margin and stock cover.",
    }


# --------------------------------------------------------------------------
# 6. Product import — "Catalog Forger" (§33, apply -> draft product)
# --------------------------------------------------------------------------

def _unique_product_slug(db: Session, base: str) -> str:
    base = re.sub(r"[^a-z0-9-]+", "-", base.lower()).strip("-") or "imported-product"
    slug, n = base, 2
    while db.query(cm.Product).filter(cm.Product.slug == slug).count():
        slug = f"{base}-{n}"
        n += 1
    return slug


def _to_num_or(v: Any, default: float) -> float:
    try:
        return float(re.sub(r"[^0-9.]", "", str(v)) or default)
    except ValueError:
        return default


def _parse_listing(text: str) -> dict[str, Any]:
    """Parse a raw supplier listing: 'Title | 95 CNY | 0.25kg | electronics | k=v; k=v'."""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    parts = re.split(r"\s*\|\s*", lines[0]) if lines else []
    title = (parts[0] if parts else "Untitled import").strip()[:255]
    cost = _to_num_or(parts[1] if len(parts) > 1 else 0, 0.0)
    currency = "CNY"
    for token in parts[1:]:
        up = token.upper()
        if "USD" in up or "$" in up:
            currency = "USD"
        elif "CNY" in up or "¥" in up or "RMB" in up:
            currency = "CNY"
    weight = next((_to_num_or(t, 0.5) for t in parts if "kg" in t.lower()), 0.5)
    category = "general"
    if len(parts) > 3:
        category = parts[3].strip().lower().replace(" ", "-") or "general"
    specs: dict[str, str] = {}
    specs_raw = next((t for t in parts if "=" in t and ";" in t), "")
    if specs_raw:
        for pair in specs_raw.split(";"):
            if "=" in pair:
                k, _, v = pair.partition("=")
                specs[k.strip()] = v.strip()
    return {"title": title, "cost": cost, "currency": currency,
            "weight_kg": weight, "category": category, "specs": specs}


def _gather_import(db: Session, params: dict) -> dict[str, Any]:
    listing = str(params.get("listing") or "").strip()
    if not listing:
        raise ValueError("params.listing is required — paste the raw supplier listing")
    parsed = _parse_listing(listing)
    supplier_id = int(params.get("supplier_id") or 0) or None
    supplier = db.get(sm.Supplier, supplier_id) if supplier_id else (
        db.query(sm.Supplier).filter(sm.Supplier.status == "verified")
        .order_by(sm.Supplier.rating.desc()).first()
    )
    breakdown = price_product(parsed["cost"], parsed["currency"], parsed["weight_kg"], None)
    slug = re.sub(r"[^a-z0-9-]+", "-", parsed["title"].lower()).strip("-")
    collision = db.query(cm.Product).filter(cm.Product.slug == slug).count() > 0
    return {
        "draft": {
            "title": parsed["title"], "slug": slug, "slug_collision": collision,
            "category": parsed["category"], "cost": parsed["cost"],
            "currency": parsed["currency"], "weight_kg": parsed["weight_kg"],
            "specs": parsed["specs"],
        },
        "supplier": {"id": supplier.id, "name": supplier.name, "rating": supplier.rating,
                     "lead_time_days": supplier.lead_time_days} if supplier else None,
        "proposed_price": {
            "ecos_price_ngn": breakdown.ecos_price_ngn,
            "waterfall": breakdown.components,
        },
    }


def _heuristic_import(gathered: dict[str, Any]) -> dict[str, Any]:
    d, price = gathered["draft"], gathered["proposed_price"]
    supplier = gathered.get("supplier")
    desc = (
        f"{d['title']} — imported via the China-Nigeria corridor"
        + (f" and quality-checked with {supplier['name']}." if supplier else ".")
        + " Delivered to your door with tracking; pay cash on delivery."
    )
    return {
        "draft_listing": {
            "title": d["title"], "slug": d["slug"], "category": d["category"],
            "description": desc, "specs": d["specs"],
            "supplier_cost": d["cost"], "currency": d["currency"],
            "weight_kg": d["weight_kg"],
        },
        "proposed_price_ngn": price["ecos_price_ngn"],
        "supplier_id": supplier["id"] if supplier else None,
        "checks": [
            "Priced through the full §12 waterfall (cost -> FX -> logistics -> fees -> margins)",
            "Created as DRAFT — a human reviews and activates it in Catalog (§9 supplier isolation)",
        ],
        "summary": f"Ready to file '{d['title']}' at ₦{price['ecos_price_ngn']:,.0f} (draft, pending review).",
    }


def _apply_import(db: Session, operator, output: dict, actor: dict) -> dict[str, Any]:
    draft = output.get("draft_listing") or {}
    title = draft.get("title") or "Untitled import"
    slug = _unique_product_slug(db, draft.get("slug") or title)
    product = cm.Product(
        supplier_id=int(output.get("supplier_id") or 0) or None,
        slug=slug, title=title,
        description=(draft.get("description") or "")[:4096],
        category=draft.get("category") or "general",
        currency=draft.get("currency") or "CNY",
        supplier_cost=float(draft.get("supplier_cost") or 0.0),
        weight_kg=float(draft.get("weight_kg") or 0.5),
        status="draft", stock=0,
        specs=draft.get("specs") or {},
        images=[f"https://picsum.photos/seed/{slug}/800/600"],
    )
    db.add(product)
    db.flush()
    return {"product_id": product.id, "slug": product.slug,
            "status": "draft (review + activate in Catalog)"}


# --------------------------------------------------------------------------
# 7. Growth operator — "Growth Pilot" (§36, advisory)
# --------------------------------------------------------------------------

def _gather_growth(db: Session, params: dict) -> dict[str, Any]:
    from app.marketing import service as attribution

    return {"report": attribution.campaign_report(db)}


def _heuristic_growth(gathered: dict[str, Any]) -> dict[str, Any]:
    report = gathered["report"]
    rows = [c for c in report["campaigns"] if c["status"] == "active"]
    with_orders = [c for c in rows if c["orders"] and c["cpa_ngn"]]
    best = min(with_orders, key=lambda c: c["cpa_ngn"]) if with_orders else None
    worst = max(with_orders, key=lambda c: c["cpa_ngn"]) if with_orders else None
    dead = [c for c in rows if not c["leads"]]

    moves: list[dict[str, Any]] = []
    if best:
        moves.append({"campaign": best["name"], "move": "scale",
                      "detail": f"Best CPA (₦{best['cpa_ngn']:,.0f}) with {best['orders']} attributed orders — raise budget 20-30% and keep the winning creative."})
    if worst and best and worst["id"] != best["id"]:
        moves.append({"campaign": worst["name"], "move": "fix_or_pause",
                      "detail": f"CPA ₦{worst['cpa_ngn']:,.0f} vs best ₦{best['cpa_ngn']:,.0f} — refresh the audience/creative before adding spend."})
    for c in dead:
        moves.append({"campaign": c["name"], "move": "investigate",
                      "detail": "Zero attributed leads — check UTM wiring on the landing page and the agent intake path."})
    top_src = (report["by_source"] or [{}])[0]
    return {
        "budget_moves": moves,
        "channel_insight": (
            f"{top_src.get('source', 'n/a')} leads convert best "
            f"({top_src.get('converted_leads', 0)}/{top_src.get('leads', 0)}) — replicate its messaging on paid channels."
            if top_src else "No source data yet."
        ),
        "totals": report["totals"],
        "summary": f"{len(moves)} budget move(s) proposed across {len(rows)} active campaign(s).",
        "rationale": "CPA from campaign spend vs attributed orders; zero-lead campaigns investigated first.",
    }


# --------------------------------------------------------------------------
# 8. Logistics operator — "Route Guard" (§37, apply -> escalations)
# --------------------------------------------------------------------------

def _now_utc():
    """Naive UTC (SQLite stores naive datetimes — keep comparisons consistent)."""
    from datetime import datetime as _dt, timezone as _tz
    return _dt.now(_tz.utc).replace(tzinfo=None)


def _gather_logistics_ops(db: Session, params: dict) -> dict[str, Any]:
    from app.logistics import models as lm_

    stall_hours = max(6, int(params.get("stall_hours") or 48))
    now = _now_utc()
    shipments = db.query(lm_.Shipment).order_by(lm_.Shipment.id.desc()).limit(200).all()
    active_states = ("processing", "in_transit", "out_for_delivery")
    rows, stalled = [], []
    for s in shipments:
        last = (
            db.query(lm_.TrackingEvent)
            .filter(lm_.TrackingEvent.shipment_id == s.id)
            .order_by(lm_.TrackingEvent.occurred_at.desc(), lm_.TrackingEvent.id.desc())
            .first()
        )
        age_h = None
        if last and last.occurred_at:
            age_h = round((now - last.occurred_at).total_seconds() / 3600, 1)
        row = {"shipment_id": s.id, "order_id": s.order_id, "tracking_code": s.tracking_code,
               "carrier": s.carrier, "status": s.status,
               "last_checkpoint": last.code if last else None,
               "hours_since_checkpoint": age_h}
        rows.append(row)
        if s.status in active_states and (age_h is None or age_h >= stall_hours):
            stalled.append(row)
    delivered_rows = [r for r in rows if r["status"] == "delivered"]
    return {
        "threshold_hours": stall_hours,
        "totals": {"tracked": len(rows), "delivered": len(delivered_rows),
                   "active": len(rows) - len(delivered_rows), "stalled": len(stalled)},
        "stalled_shipments": stalled,
    }


def _heuristic_logistics_ops(gathered: dict[str, Any]) -> dict[str, Any]:
    totals = gathered["totals"]
    escalations = [
        {"shipment_id": s["shipment_id"], "tracking_code": s["tracking_code"],
         "action": "probe_carrier_and_notify_customer",
         "detail": (
             f"No checkpoint advance in {s['hours_since_checkpoint'] if s['hours_since_checkpoint'] is not None else 'unknown'}h "
             f"(threshold {gathered['threshold_hours']}h). Last checkpoint: {s['last_checkpoint'] or 'none'}. "
             "Ping the carrier lane, then message the customer with an honest ETA."
         )}
        for s in gathered["stalled_shipments"]
    ]
    return {
        "escalations": escalations,
        "totals": totals,
        "summary": (
            f"{totals['stalled']} of {totals['active']} active shipment(s) breached the "
            f"{gathered['threshold_hours']}h checkpoint SLA; delivered {totals['delivered']}/{totals['tracked']}."
        ),
        "rationale": "Checkpoint freshness is the corridor's honest health signal — silence means trouble.",
    }


def _apply_logistics_ops(db: Session, operator, output: dict, actor: dict) -> dict[str, Any]:
    from app.notifications import service as notif_service

    raised = []
    for esc in output.get("escalations", []):
        rows = notif_service.notify(
            db,
            org_id=operator.org_id, category="shipments", level="warning",
            title=f"Shipment {esc.get('tracking_code', esc.get('shipment_id'))} stalled",
            body=str(esc.get("detail", ""))[:1024],
            entity_type="shipment", entity_id=int(esc.get("shipment_id") or 0) or None,
            meta={"operator": operator.code},
        )
        raised.append({"shipment_id": esc.get("shipment_id"), "notifications": len(rows)})
    return {"escalations_raised": raised}


# --------------------------------------------------------------------------
# 9. Business analyst — "P&L Analyst" (§38, advisory)
# --------------------------------------------------------------------------

def _gather_analyst(db: Session, params: dict) -> dict[str, Any]:
    from app.finance import models as fm
    from app.returns import models as rm
    from app.settlements import service as settlement_service

    by_type = dict(
        db.query(fm.LedgerEntry.entry_type, sa_func.sum(fm.LedgerEntry.amount))
        .group_by(fm.LedgerEntry.entry_type).all()
    )
    by_type = {k: round(float(v or 0.0), 2) for k, v in by_type.items()}
    total_orders = db.query(sa_func.count(om.Order.id)).scalar() or 0
    delivered = db.query(sa_func.count(om.Order.id)).filter(om.Order.status == "delivered").scalar() or 0
    problem = (
        db.query(sa_func.count(om.Order.id))
        .filter(om.Order.status.in_(["cancelled", "failed", "returned", "refunded"]))
        .scalar() or 0
    )
    rmas = db.query(sa_func.count(rm.ReturnOrder.id)).scalar() or 0
    units_sold = db.query(sa_func.coalesce(sa_func.sum(om.OrderItem.qty), 0)).scalar() or 0
    try:
        unsettled = settlement_service.unsettled_summary(db)
    except Exception:  # noqa: BLE001 — analytics must not depend on settlement state
        unsettled = {"total_amount": 0.0, "entry_count": 0}
    return {
        "ledger_totals_by_type": by_type,
        "orders": {"total": total_orders, "delivered": delivered, "problem": problem},
        "returns": {"rma_count": rmas, "units_sold": int(units_sold)},
        "unsettled_obligations": {"amount": unsettled.get("total_amount", 0.0),
                                  "entries": unsettled.get("entry_count", 0)},
    }


def _heuristic_analyst(gathered: dict[str, Any]) -> dict[str, Any]:
    led = gathered["ledger_totals_by_type"]
    revenue = led.get("customer_payment", 0.0)
    refunds = led.get("refund", 0.0)
    supplier = abs(led.get("supplier_payable", 0.0))
    logistics = abs(led.get("logistics_cost", 0.0))
    paycost = abs(led.get("payment_cost", 0.0))
    luxeen = abs(led.get("luxeen_economics", 0.0))
    operator = led.get("operator_economics", 0.0)
    net = revenue + refunds  # refunds arrive pre-signed (negative)
    contribution = net - supplier - logistics - paycost - luxeen

    orders = gathered["orders"]
    delivery_rate = round(orders["delivered"] / orders["total"], 3) if orders["total"] else 0.0
    rma = gathered["returns"]
    return_rate = round(rma["rma_count"] / orders["total"], 3) if orders["total"] else 0.0
    unsettled = gathered["unsettled_obligations"]

    risks: list[str] = []
    if delivery_rate < 0.5 and orders["total"] >= 5:
        risks.append(f"Delivery rate is {delivery_rate:.0%} — cash is stuck in the pipeline; chase the in-flight orders.")
    if return_rate > 0.15:
        risks.append(f"Return rate {return_rate:.0%} is above the 15% comfort line — inspect the top-returned SKUs.")
    if unsettled["amount"] > 0:
        risks.append(f"₦{unsettled['amount']:,.0f} across {unsettled['entries']} ledger entries is still unsettled — counterparties are waiting.")
    if not risks:
        risks.append("No red flags: pipeline, returns and settlements all look healthy this period.")

    highlights = [
        f"Gross collections ₦{revenue:,.0f}; net after refunds ₦{net:,.0f}.",
        f"Contribution after supplier/logistics/fees/Luxeen: ₦{contribution:,.0f} "
        f"({(contribution / net * 100 if net else 0):.1f}% of net).",
        f"Operator economics so far: ₦{operator:,.0f}.",
    ]
    return {
        "highlights": highlights,
        "risks": risks,
        "recommendations": [
            "Reconcile the settlement queue weekly — stale payables erode supplier trust and lane priority.",
            "Watch the stockout-risk SKUs; a stockout on a proven mover costs more than a PO.",
            "Keep COD confirmations fast: every hour between order and confirmation raises the cancel rate.",
        ],
        "metrics": {
            "net_revenue_ngn": round(net, 2), "contribution_ngn": round(contribution, 2),
            "delivery_rate": delivery_rate, "return_rate": return_rate,
            "unsettled_ngn": unsettled["amount"],
        },
        "summary": f"Net ₦{net:,.0f}, contribution ₦{contribution:,.0f}, {len(risks)} risk note(s).",
    }


# --------------------------------------------------------------------------
# 10. Landing page operator — "Page Architect" (§34)
# --------------------------------------------------------------------------

CATEGORY_THEMES = {
    "electronics": "#0ea5e9", "home-appliances": "#f59e0b", "fashion": "#ec4899",
    "beauty": "#d946ef", "fitness": "#16a34a", "gadgets": "#8b5cf6",
}


def _age_hours(dt) -> float:
    """SQLite-friendly age in hours (naive timestamps treated as UTC)."""
    if dt is None:
        return 0.0
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (now - dt).total_seconds() / 3600.0)


def _angle_for(price_ngn: float, units: int, repeat_share: float, source_mix: dict) -> tuple[str, str]:
    """Deterministic selling-angle pick from live audience signals (§34)."""
    paid = sum(v for k, v in source_mix.items() if k in ("meta_ads", "tiktok", "google_ads"))
    total = sum(source_mix.values()) or 1
    if repeat_share >= 0.30:
        return "replenishment-loyalty", "a third or more of its buyers already came back — sell convenience and restock"
    if price_ngn >= 25000:
        return "premium-quality", f"ticket size ₦{price_ngn:,.0f} — buyers need quality justification, not discounting"
    if paid / total >= 0.6:
        return "problem-agitate-solve", "over 60% of its audience arrives from paid social — classic COD problem/solution flow"
    if units == 0:
        return "launch-value", "no sales yet — lead with an introductory value story"
    return "value-cod", "steady organic interest — value-for-money plus COD trust converts this profile"


def _gather_landing(db: Session, params: dict) -> dict[str, Any]:
    p = db.get(cm.Product, int(params.get("product_id", 0)))
    if p is None:
        raise ValueError("product_id not found")
    b = price_product(p.supplier_cost, "CNY", p.weight_kg, p.markup_pct)
    sales = _sales_snapshot(db).get(p.id, {"units": 0, "revenue": 0.0})

    leads = db.query(crm_m.Lead).filter(crm_m.Lead.product_id == p.id).all()
    source_mix: dict[str, int] = {}
    status_mix: dict[str, int] = {}
    for l in leads:
        source_mix[l.source] = source_mix.get(l.source, 0) + 1
        status_mix[l.status] = status_mix.get(l.status, 0) + 1

    # repeat buyers across the network, and which of this product's buyers repeat
    repeat_ids = {
        row[0] for row in (
            db.query(om.Order.customer_id)
            .filter(om.Order.status.notin_(["draft", "cancelled", "failed"]))
            .group_by(om.Order.customer_id)
            .having(sa_func.count(om.Order.id) >= 2)
            .all()
        ) if row[0] is not None
    }
    buyers = {
        row[0] for row in (
            db.query(om.Order.customer_id)
            .join(om.OrderItem, om.OrderItem.order_id == om.Order.id)
            .filter(
                om.OrderItem.product_id == p.id,
                om.Order.status.notin_(["draft", "cancelled", "failed"]),
            )
            .distinct().all()
        ) if row[0] is not None
    }
    repeat_share = (len(buyers & repeat_ids) / len(buyers)) if buyers else 0.0

    variants = [
        {"id": v.id, "sku": v.sku, "option_name": v.option_name,
         "option_value": v.option_value, "cost_delta": v.cost_delta, "stock": v.stock}
        for v in db.query(cm.ProductVariant)
        .filter(cm.ProductVariant.product_id == p.id, cm.ProductVariant.status == "active")
        .all()
    ]

    angle, angle_why = _angle_for(b.ecos_price_ngn, sales["units"], repeat_share, source_mix)
    if params.get("angle"):
        angle = str(params["angle"])[:40]

    return {
        "product": {
            "id": p.id, "title": p.title, "slug": p.slug, "category": p.category,
            "description": p.description, "specs": p.specs, "stock": p.stock,
            "price_ngn": b.ecos_price_ngn,
            "image": p.images[0] if p.images else f"https://picsum.photos/seed/{p.slug}/1600/900",
        },
        "audience": {
            "lead_sources": source_mix, "lead_statuses": status_mix,
            "buyers": len(buyers), "repeat_buyer_share": round(repeat_share, 2),
            "units_sold": sales["units"],
            "angle": angle, "angle_rationale": angle_why,
            "angle_hint_from_operator": params.get("angle") or None,
        },
        "variants": variants,
    }


def _heuristic_landing(gathered: dict[str, Any]) -> dict[str, Any]:
    p, aud = gathered["product"], gathered["audience"]
    angle = aud["angle"]
    slug = p["slug"] or f"product-{p['id']}"
    cat = (p["category"] or "electronics").lower()
    theme = {"primary": CATEGORY_THEMES.get(cat, "#0ea5e9")}
    utm = f"?utm_source=lp&utm_medium={angle}&utm_campaign={slug}-launch"
    href = f"/products/{slug}{utm}"

    angle_copy = {
        "replenishment-loyalty": (
            f"{p['title']} — back in stock, because you asked",
            f"You already know it: {p['title']} keeps selling out. ₦{p['price_ngn']:,.0f}, pay cash on delivery.",
        ),
        "premium-quality": (
            f"{p['title']} — built to outlast the price tag",
            f"A ₦{p['price_ngn']:,.0f} investment in quality you can verify on delivery — before you pay a naira.",
        ),
        "problem-agitate-solve": (
            f"Still struggling with {cat.replace('-', ' ')} that disappoint?",
            f"{p['title']} fixes it — ₦{p['price_ngn']:,.0f}, checked at your door, pay only when it delivers.",
        ),
        "launch-value": (
            f"New: {p['title']} — launch price",
            f"First batch just landed from our China network. ₦{p['price_ngn']:,.0f} — pay on delivery.",
        ),
    }.get(angle, (
        f"{p['title']} — delivered to your door",
        f"₦{p['price_ngn']:,.0f} — quality-checked, tracked, and you pay cash on delivery.",
    ))
    headline, subheadline = angle_copy

    specs = p.get("specs") or {}
    feature_items = "\n".join(
        f"★ | {k.replace('_', ' ').title()} | {v}" for k, v in list(specs.items())[:6]
    ) or "★ | Quality checked | Every unit is inspected before it leaves our China hub"

    blocks = [
        {"type": "hero", "headline": headline, "subheadline": subheadline,
         "cta_label": "Order now — pay on delivery", "cta_href": href, "image": p["image"]},
        {"type": "trust_badges",
         "items": "💵 | Pay on delivery\n🚚 | Tracked door-to-door\n↩️ | 7-day returns\n✅ | Quality checked"},
        {"type": "image_text", "image": p["image"], "image_side": "right",
         "title": f"Why the {p['title']} works",
         "body": (p["description"] or f"The {p['title']} is sourced through the Ecos China→Nigeria network.") +
                 " Every unit ships with door-to-door tracking, and payment happens only when it arrives."},
    ]
    if feature_items:
        blocks.append({"type": "feature_grid", "title": "What you get", "items": feature_items})
    blocks.extend([
        {"type": "testimonials", "title": "Buyers across Nigeria",
         "items": ("Chidi, Lagos | Paid on delivery and the item matched the photos exactly.\n"
                   "Amina, Abuja | Arrived in 9 days with tracking the whole way.\n"
                   "Tunde, Ibadan | The return window made trying it risk-free.")},
        {"type": "faq", "title": "Questions, answered",
         "items": ("When do I pay? | Only when the order reaches your door — cash on delivery.\n"
                   "How long is delivery? | Typically 7-14 days from our China hub, fully tracked.\n"
                   "What if I don't like it? | You have 7 days to return it, no questions asked.\n"
                   "Is it original? | Every unit is quality-checked before shipping.")},
        {"type": "cta", "title": "Ready when you are",
         "body": f"₦{p['price_ngn']:,.0f} — {subheadline.split('—')[-1].strip()}",
         "cta_label": "Order now — pay on delivery", "cta_href": href},
        {"type": "product_showcase", "title": "More from the store", "mode": "latest", "limit": "3"},
    ])

    return {
        "page": {
            "title": f"{p['title']} — {angle.replace('-', ' ').title()} page",
            "slug": slug, "theme": theme, "blocks": blocks,
            "seo": {
                "title": f"{p['title']} | Pay on delivery in Nigeria",
                "description": subheadline[:160],
            },
        },
        "selling_angle": {"angle": angle, "audience": aud, "rationale": aud["angle_rationale"]},
        "tracking": {
            "utm_source": "lp", "utm_medium": angle, "utm_campaign": f"{slug}-launch",
            "cta_href": href,
            "note": "CTAs carry UTM so §16 attribution credits this page's traffic and orders.",
        },
        "copy_notes": (
            f"{angle.replace('-', ' ').title()} angle: {aud['angle_rationale']}. "
            "COD trust signals (pay-on-delivery, returns, tracking) repeated at hero, badges, FAQ and final CTA."
        ),
        "summary": (
            f"Full landing page for {p['title']} using the {angle.replace('-', ' ')} angle: "
            f"{len(blocks)} blocks, UTM-tagged CTAs, ready to edit and publish."
        ),
    }


def _apply_landing(db: Session, operator, output: dict, actor: dict) -> dict[str, Any]:
    from app.landing_pages.blocks import sanitize_blocks  # local: cycle-safe

    product = db.get(cm.Product, output.get("_product_id", 0))
    if product is None:
        raise ValueError("proposal product no longer exists")
    page_prop = output.get("page") or {}
    raw_blocks = page_prop.get("blocks") or []
    clean_blocks, errors = sanitize_blocks(raw_blocks)
    if errors:
        raise ValueError("AI page failed block validation: " + "; ".join(errors[:5]))
    if not clean_blocks:
        raise ValueError("AI page proposal contained no usable blocks")

    base_slug = page_prop.get("slug") or product.slug or f"product-{product.id}"
    page = lpm.LandingPage(
        org_id=operator.org_id,
        slug=_unique_page_slug(db, f"{re.sub(r'[^a-z0-9-]+', '-', base_slug.lower()).strip('-') or 'product'}-ai"),
        title=(page_prop.get("title") or f"{product.title} — AI page")[:255],
        status="draft",  # §34: the operator reviews/modifies/publishes in the editor
        blocks=clean_blocks,
        theme=page_prop.get("theme") or {"primary": "#0ea5e9"},
        seo=page_prop.get("seo") or {"title": product.title, "description": ""},
        created_by=actor.get("user_id"),
    )
    db.add(page)
    db.flush()
    events.publish(db, "landing_page.created", {
        "page_id": page.id, "slug": page.slug, "org_id": operator.org_id,
        "source": "ai_landing_page_architect",
    })
    return {
        "landing_page_id": page.id, "slug": page.slug, "status": "draft",
        "block_count": len(clean_blocks),
        "next_step": "Landing Pages → open the draft → edit → publish (or schedule)",
    }


# --------------------------------------------------------------------------
# 11. Customer operations operator — "Customer Sentinel" (§35)
# --------------------------------------------------------------------------

def _gather_customer_ops(db: Session, params: dict) -> dict[str, Any]:
    from app.returns import models as rm  # cycle-safe local import
    from app.storefront import models as stm

    stale_lead_days = float(params.get("stale_lead_days", 2) or 2)
    stale_order_hours = float(params.get("stale_order_hours", 12) or 12)

    leads = db.query(crm_m.Lead).all()
    products = {p.id: p.title for p in db.query(cm.Product).all()}
    orders = db.query(om.Order).all()
    order_creators = {}
    for o in orders:
        order_creators.setdefault(o.lead_id, o.id)

    def lead_item(l: crm_m.Lead) -> dict:
        return {"lead_id": l.id, "name": l.contact_name, "phone": l.contact_phone,
                "product": products.get(l.product_id), "status": l.status,
                "age_hours": round(_age_hours(l.created_at), 1)}

    by_status: dict[str, list] = {}
    for l in leads:
        by_status.setdefault(l.status, []).append(l)

    new_leads = [lead_item(l) for l in sorted(by_status.get("new", []), key=lambda x: x.created_at)]
    abandoned = [
        lead_item(l) for l in sorted(by_status.get("contacted", []) + by_status.get("interested", []),
                                     key=lambda x: x.created_at)
        if _age_hours(l.created_at) >= stale_lead_days * 24 and l.id not in order_creators
    ]
    unreachable = [lead_item(l) for l in by_status.get("unreachable", [])]

    pending = [
        {"order_id": o.id, "customer_id": o.customer_id, "total": o.total,
         "age_hours": round(_age_hours(o.created_at), 1), "stale": _age_hours(o.created_at) > stale_order_hours}
        for o in sorted(orders, key=lambda x: x.created_at)
        if o.status == "pending_confirmation"
    ]
    failed = [
        {"order_id": o.id, "total": o.total, "age_hours": round(_age_hours(o.created_at), 1)}
        for o in sorted(orders, key=lambda x: x.created_at) if o.status == "failed"
    ]

    # repeat customers (2+ live orders) with spend
    spend: dict[int, float] = {}
    count: dict[int, int] = {}
    for o in orders:
        if o.status in ("draft", "cancelled", "failed"):
            continue
        spend[o.customer_id] = spend.get(o.customer_id, 0.0) + (o.total or 0.0)
        count[o.customer_id] = count.get(o.customer_id, 0) + 1
    repeat = [
        {"customer_id": cid, "orders": n, "lifetime_spend": round(spend[cid], 2)}
        for cid, n in sorted(count.items(), key=lambda kv: -kv[1]) if n >= 2
    ]

    open_rmaseq = (
        db.query(rm.ReturnOrder)
        .filter(rm.ReturnOrder.status.in_(["requested", "approved"]))
        .order_by(rm.ReturnOrder.created_at.asc()).all()
    )
    support = [
        {"rma_id": r.id, "rma_number": r.rma_number, "order_id": r.order_id,
         "reason": r.reason, "status": r.status,
         "age_hours": round(_age_hours(r.created_at), 1)}
        for r in open_rmaseq
    ]

    store_org = {s.id: s.org_id for s in db.query(stm.Store).all()}
    buckets = {
        "new_leads": new_leads, "abandoned_opportunities": abandoned,
        "pending_confirmations": pending, "unreachable_customers": unreachable,
        "failed_deliveries": failed, "repeat_customers": repeat[:10],
        "support_issues": support,
    }
    # pick the org owning the most orders (service auto-copies {"org": {"id":..}}
    # onto the output as _org_id for the apply step)
    orders_per_org: dict[int, int] = {}
    for o in orders:
        org = store_org.get(o.store_id)
        if org is not None:
            orders_per_org[org] = orders_per_org.get(org, 0) + 1
    if not orders_per_org and store_org:
        orders_per_org[next(iter(store_org.values()))] = 0
    top_org = max(orders_per_org, key=lambda k: orders_per_org[k]) if orders_per_org else None
    return {
        "org": {"id": top_org} if top_org else {},
        "buckets": buckets,
        "thresholds": {"stale_lead_days": stale_lead_days, "stale_order_hours": stale_order_hours},
    }


def _heuristic_customer_ops(gathered: dict[str, Any]) -> dict[str, Any]:
    b = gathered["buckets"]
    labels = {
        "new_leads": ("New leads awaiting first contact", "info",
                      "Call each new lead today — conversion decays fast after the first hour."),
        "abandoned_opportunities": ("Abandoned opportunities", "warning",
                                    "Re-engage with a short nudge: stock is limited, COD still available."),
        "pending_confirmations": ("Pending confirmations", "warning",
                                  "Confirm or release stale orders — every idle COD order blocks inventory."),
        "unreachable_customers": ("Unreachable customers", "critical",
                                  "Attempt a different channel (WhatsApp), then close as lost after 3 tries."),
        "failed_deliveries": ("Failed deliveries", "critical",
                              "Coordinate re-delivery with the courier before the customer complains."),
        "repeat_customers": ("Repeat customers", "success",
                             "Send a WhatsApp re-engagement blast with a returning-customer bundle."),
        "support_issues": ("Open support issues (RMAs)", "warning",
                           "Approve/reject pending RMAs today — silent RMAs poison trust and reviews."),
    }
    watchlist = []
    for key, (label, priority, action) in labels.items():
        items = b.get(key) or []
        watchlist.append({
            "bucket": key, "label": label, "priority": priority,
            "count": len(items), "recommended_action": action, "items": items[:8],
        })
    playbook = [
        {"action": "notify_ops", "bucket": w["bucket"], "priority": w["priority"],
         "message": w["recommended_action"]}
        for w in watchlist if w["count"] > 0 and w["priority"] in ("critical", "warning")
    ]
    hot = [w for w in watchlist if w["priority"] == "critical" and w["count"] > 0]
    active = [w for w in watchlist if w["count"] > 0]
    summary = (
        f"{len(hot)} critical bucket(s)"
        + (": " + ", ".join(f"{w['label']} ({w['count']})" for w in hot) + ". " if hot else ". ")
        + "Watchlist: "
        + (", ".join(f"{w['label']} {w['count']}" for w in active) or "all clear")
        + "."
    )
    return {
        "watchlist": watchlist, "playbook": playbook,
        "totals": {key: len(b.get(key) or []) for key in labels},
        "summary": summary,
    }


def _apply_customer_ops(db: Session, operator, output: dict, actor: dict) -> dict[str, Any]:
    from app.notifications import service as notif_svc  # cycle-safe local import

    org_id = output.get("_org_id") or operator.org_id
    playbook = output.get("playbook") or []
    executed = []
    notified = 0
    for step in playbook:
        bucket = step.get("bucket")
        watch = next((w for w in output.get("watchlist", []) if w.get("bucket") == bucket), None)
        if not watch or not watch.get("count"):
            continue
        level = {"critical": "critical", "warning": "warning", "success": "success"}.get(
            watch.get("priority"), "info")
        lines = []
        for item in (watch.get("items") or [])[:5]:
            if bucket in ("pending_confirmations",):
                lines.append(f"Order #{item.get('order_id')} — ₦{item.get('total', 0):,.0f}, waiting {item.get('age_hours', 0):.0f}h")
            elif bucket in ("new_leads", "abandoned_opportunities", "unreachable_customers"):
                lines.append(f"{item.get('name')} ({item.get('phone')}) — {item.get('product') or 'product'}, {item.get('status')}")
            elif bucket == "failed_deliveries":
                lines.append(f"Order #{item.get('order_id')} failed delivery")
            elif bucket == "support_issues":
                lines.append(f"{item.get('rma_number')} — {item.get('reason')} ({item.get('status')})")
            elif bucket == "repeat_customers":
                lines.append(f"Customer #{item.get('customer_id')} — {item.get('orders')} orders, ₦{item.get('lifetime_spend', 0):,.0f}")
        title = f"Customer Ops — {watch.get('label')}: {watch.get('count')}"
        body = (watch.get("recommended_action") or "") + ("\n" + "\n".join(lines) if lines else "")
        category = {
            "pending_confirmations": "orders", "failed_deliveries": "shipments",
            "support_issues": "returns", "repeat_customers": "crm",
        }.get(bucket, "crm")
        rows = notif_svc.notify(
            db, org_id=org_id, category=category, level=level,
            title=title, body=body[:1024],
            entity_type="ai_run", entity_id=step.get("run_id"),
            meta={"source": "customer_sentinel", "bucket": bucket},
        )
        notified += len(rows)
        executed.append({"bucket": bucket, "action": "notify_ops", "level": level,
                         "notifications": len(rows)})

    return {
        "actions_executed": executed, "notifications_sent": notified,
        "note": "Playbook = safe ops notifications. Calls/re-deliveries stay human (§39 governance).",
    }


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
    "product_research": {
        "code": "product_research",
        "name": "Market Scout",
        "role_description": "Researches the catalog for scale-now winners, dormant sleepers and category gaps (§32). Advisory only.",
        "advisory": True,
        "input_fields": [],
        "gather": _gather_research,
        "heuristic": _heuristic_research,
        "apply": None,
        "task_brief": (
            "You are Market Scout, a product research analyst for a China->Nigeria corridor. "
            "Using the velocity/margin snapshot, surface scale-now winners, sleepers worth "
            "reviving, and category gaps worth sourcing. Respond ONLY with JSON: "
            "{\"opportunities\": {\"scale_now\": [...], \"revive\": [...], \"category_gaps\": [...]}, "
            "\"summary\": str, \"rationale\": str}"
        ),
    },
    "product_import": {
        "code": "product_import",
        "name": "Catalog Forger",
        "role_description": "Parses a raw supplier listing into a structured draft product priced by the waterfall; approval files it in Catalog (§33).",
        "advisory": False,
        "input_fields": [
            {"key": "listing", "label": "Raw supplier listing", "type": "text", "required": True,
             "placeholder": "Mini Projector HD | 210 CNY | 1.4kg | electronics | warranty=6 months; resolution=1080p"},
            {"key": "supplier_id", "label": "Supplier (optional — defaults to best-rated)", "type": "number", "required": False},
        ],
        "gather": _gather_import,
        "heuristic": _heuristic_import,
        "apply": _apply_import,
        "task_brief": (
            "You are Catalog Forger, a catalog operations specialist. Turn the parsed supplier "
            "listing into a clean draft listing with a customer-facing description. Respond ONLY "
            "with JSON: {\"draft_listing\": {\"title\": str, \"slug\": str, \"category\": str, "
            "\"description\": str, \"specs\": {...}, \"supplier_cost\": number, \"currency\": str, "
            "\"weight_kg\": number}, \"proposed_price_ngn\": number, \"supplier_id\": int, "
            "\"checks\": [str], \"summary\": str}"
        ),
    },
    "growth_operator": {
        "code": "growth_operator",
        "name": "Growth Pilot",
        "role_description": "Reads the attribution report and proposes concrete budget moves per campaign/channel (§36). Advisory only.",
        "advisory": True,
        "input_fields": [],
        "gather": _gather_growth,
        "heuristic": _heuristic_growth,
        "apply": None,
        "task_brief": (
            "You are Growth Pilot, a growth marketer for COD e-commerce. Using the attribution "
            "report, propose budget moves (scale / fix_or_pause / investigate) and one channel "
            "insight. Respond ONLY with JSON: {\"budget_moves\": [{\"campaign\": str, \"move\": str, "
            "\"detail\": str}], \"channel_insight\": str, \"totals\": {...}, \"summary\": str, "
            "\"rationale\": str}"
        ),
    },
    "logistics_operator": {
        "code": "logistics_operator",
        "name": "Route Guard",
        "role_description": "Watches shipment checkpoint freshness and escalates stalled lanes; approval raises ops notifications (§37).",
        "advisory": False,
        "input_fields": [{"key": "stall_hours", "label": "Stall threshold (hours)", "type": "number", "required": False}],
        "gather": _gather_logistics_ops,
        "heuristic": _heuristic_logistics_ops,
        "apply": _apply_logistics_ops,
        "task_brief": (
            "You are Route Guard, a logistics escalation manager. Using shipment checkpoint data, "
            "flag shipments that breached the stall threshold and propose next actions. Respond "
            "ONLY with JSON: {\"escalations\": [{\"shipment_id\": int, \"tracking_code\": str, "
            "\"action\": str, \"detail\": str}], \"totals\": {...}, \"summary\": str, \"rationale\": str}"
        ),
    },
    "business_analyst": {
        "code": "business_analyst",
        "name": "P&L Analyst",
        "role_description": "Compiles a ledger-grounded P&L digest with highlights, risks and recommendations (§38). Advisory only.",
        "advisory": True,
        "input_fields": [],
        "gather": _gather_analyst,
        "heuristic": _heuristic_analyst,
        "apply": None,
        "task_brief": (
            "You are the Business Analyst for a cross-border e-commerce corridor. Using the ledger "
            "totals and order stats, produce a digest: highlights, risks, recommendations, metrics. "
            "Respond ONLY with JSON: {\"highlights\": [str], \"risks\": [str], \"recommendations\": [str], "
            "\"metrics\": {...}, \"summary\": str}"
        ),
    },
    "landing_page_architect": {
        "code": "landing_page_architect",
        "name": "Page Architect",
        "role_description": "Builds a complete landing page — angle, copy, blocks, CTA, UTM tracking — from a product; approval files it as an editable draft (§34).",
        "advisory": False,
        "input_fields": [
            {"key": "product_id", "label": "Product", "type": "number", "required": True},
            {"key": "angle", "label": "Selling angle override (optional)", "type": "text", "required": False,
             "placeholder": "value-cod | premium-quality | problem-agitate-solve | launch-value | replenishment-loyalty"},
        ],
        "gather": _gather_landing,
        "heuristic": _heuristic_landing,
        "apply": _apply_landing,
        "task_brief": (
            "You are Page Architect, a conversion landing-page designer for COD e-commerce. "
            "Using the product and audience snapshot, pick the strongest selling angle and compose "
            "a full page: hero, trust badges, image+text story, feature grid, testimonials, FAQ, "
            "closing CTA and a product showcase. Every CTA carries the tracking UTM. Respond ONLY "
            "with JSON: {\"page\": {\"title\": str, \"slug\": str, \"theme\": {\"primary\": str}, "
            "\"blocks\": [{\"type\": str, ...fields}], \"seo\": {...}}, \"selling_angle\": {...}, "
            "\"tracking\": {...}, \"copy_notes\": str, \"summary\": str}"
        ),
    },
    "customer_ops": {
        "code": "customer_ops",
        "name": "Customer Sentinel",
        "role_description": "Watches the 7 customer-operations buckets — new leads, abandoned opportunities, pending confirmations, unreachable customers, failed deliveries, repeat customers, support issues — and runs the safe ops playbook on approval (§35).",
        "advisory": False,
        "input_fields": [
            {"key": "stale_lead_days", "label": "Stale lead threshold (days)", "type": "number", "required": False},
            {"key": "stale_order_hours", "label": "Stale order threshold (hours)", "type": "number", "required": False},
        ],
        "gather": _gather_customer_ops,
        "heuristic": _heuristic_customer_ops,
        "apply": _apply_customer_ops,
        "task_brief": (
            "You are Customer Sentinel, the customer-operations watcher. Using the bucket snapshot, "
            "prioritise what needs action today and produce a watchlist with a recommended action "
            "per bucket, plus a safe playbook (ops notifications only). Respond ONLY with JSON: "
            "{\"watchlist\": [{\"bucket\": str, \"label\": str, \"priority\": str, \"count\": int, "
            "\"recommended_action\": str, \"items\": [...]}], \"playbook\": [{\"action\": str, "
            "\"bucket\": str, \"message\": str}], \"totals\": {...}, \"summary\": str}"
        ),
    },
}
