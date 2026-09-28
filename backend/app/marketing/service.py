"""Marketing attribution service (plan §16).

Every lead carries its acquisition context: `source` (channel), `campaign`
(free-text) and a raw `utm` JSON payload captured on the storefront. When a
lead is created we resolve it to a Campaign row via the `utm_campaign` key
(first-touch on the public side, last-touch from sessionStorage on repeat
visits) so the board, the P&L view and this report all agree on "where did
this lead / order / naira come from".
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.crm import models as crm_m
from app.marketing import models as m
from app.orders import models as om

# statuses that count as "the lead became revenue"
UNPAID_EXITS = {"unreachable", "cancelled"}
CONVERTED_STATUSES = {
    "order_created", "confirmed", "fulfilled", "delivered", "returned", "refunded",
}

UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"]


def normalize_utm(raw: dict | None) -> dict:
    """Keep only known UTM keys + landing page context, stringified."""
    if not raw:
        return {}
    out: dict[str, str] = {}
    for k in UTM_KEYS + ["landing_page", "referrer"]:
        v = raw.get(k)
        if v:
            out[k] = str(v)[:255]
    return out


def resolve_campaign_id(db: Session, source: str, campaign: str, utm: dict | None) -> int | None:
    """Map (utm_campaign, campaign text, source) -> Campaign.id, or None."""
    key = ""
    if utm and utm.get("utm_campaign"):
        key = utm["utm_campaign"].strip().lower()
    elif campaign and campaign.strip():
        key = campaign.strip().lower()

    if key:
        hit = (
            db.query(m.Campaign)
            .filter(m.Campaign.utm_campaign == key)
            .first()
        )
        if hit:
            return hit.id

    # fallback: single active campaign on this channel (e.g. storefront + tiktok)
    if source:
        hits = (
            db.query(m.Campaign)
            .filter(m.Campaign.channel == source, m.Campaign.status == "active")
            .all()
        )
        if len(hits) == 1:
            return hits[0].id
    return None


def campaign_report(db: Session) -> dict:
    """The §16 attribution report: per-campaign, per-source, totals."""
    leads = db.query(crm_m.Lead).all()
    orders = db.query(om.Order).all()

    orders_by_lead: dict[int | None, list[om.Order]] = {}
    for o in orders:
        orders_by_lead.setdefault(o.lead_id, []).append(o)

    def revenue_for(lead_ids: list[int | None]) -> tuple[int, float]:
        sel = [o for lid in lead_ids for o in orders_by_lead.get(lid, [])]
        live = [o for o in sel if o.status not in ("cancelled", "failed")]
        return len(live), round(sum(o.total for o in live), 2)

    campaigns = db.query(m.Campaign).order_by(m.Campaign.id).all()
    campaign_rows = []
    attributed_lead_ids: set[int] = set()
    for c in campaigns:
        c_leads = [l for l in leads if l.campaign_id == c.id]
        attributed_lead_ids.update(l.id for l in c_leads)
        converted = [l for l in c_leads if l.customer_id or l.status in CONVERTED_STATUSES]
        orders_n, revenue = revenue_for([l.id for l in c_leads])
        spend = c.budget_ngn or 0.0
        campaign_rows.append({
            "id": c.id, "name": c.name, "channel": c.channel, "status": c.status,
            "utm_campaign": c.utm_campaign, "landing_page_slug": c.landing_page_slug,
            "spend_ngn": spend,
            "leads": len(c_leads),
            "converted_leads": len(converted),
            "conversion_rate": round(len(converted) / len(c_leads), 4) if c_leads else 0.0,
            "orders": orders_n,
            "revenue_ngn": revenue,
            "cpa_ngn": round(spend / orders_n, 2) if orders_n and spend else None,
            "cost_per_lead_ngn": round(spend / len(c_leads), 2) if c_leads and spend else None,
        })

    # per-source breakdown (includes storefront + organic leads w/o campaign)
    sources: dict[str, list[crm_m.Lead]] = {}
    for l in leads:
        sources.setdefault(l.source or "unknown", []).append(l)
    source_rows = []
    for src, s_leads in sorted(sources.items(), key=lambda kv: -len(kv[1])):
        converted = [l for l in s_leads if l.customer_id or l.status in CONVERTED_STATUSES]
        orders_n, revenue = revenue_for([l.id for l in s_leads])
        source_rows.append({
            "source": src, "leads": len(s_leads), "converted_leads": len(converted),
            "orders": orders_n, "revenue_ngn": revenue,
        })

    # orders placed without any lead (manual operator intake) = direct
    direct_orders_n, direct_revenue = revenue_for([None])
    if direct_orders_n:
        source_rows.append({
            "source": "direct", "leads": 0, "converted_leads": 0,
            "orders": direct_orders_n, "revenue_ngn": direct_revenue,
        })

    total_leads = len(leads)
    total_converted = len([l for l in leads if l.customer_id or l.status in CONVERTED_STATUSES])
    _, total_revenue = revenue_for([l.id for l in leads])
    total_spend = sum(c.budget_ngn or 0.0 for c in campaigns)
    direct_orders_all = [o for o in orders if o.lead_id is None and o.status not in ("cancelled", "failed")]

    return {
        "campaigns": campaign_rows,
        "by_source": source_rows,
        "totals": {
            "leads": total_leads,
            "converted_leads": total_converted,
            "conversion_rate": round(total_converted / total_leads, 4) if total_leads else 0.0,
            "revenue_ngn": round(total_revenue + sum(o.total for o in direct_orders_all), 2),
            "spend_ngn": round(total_spend, 2),
            "attributed_lead_pct": round(len(attributed_lead_ids) / total_leads, 4) if total_leads else 0.0,
        },
    }


def lead_utm_dict(lead: crm_m.Lead) -> dict:
    try:
        return json.loads(lead.utm or "{}")
    except Exception:  # noqa: BLE001
        return {}
