"""Economics resolution (plan §57 — the flexible economic model).

The waterfall's rates are DATA, not code:

    resolve_profile(db, org_id=..., corridor=..., category=...)
        -> best-matching active WaterfallProfile (specificity, then priority),
           merged over the static corridor defaults

    compute_waterfall(..., profile=..., rate_card=...)
        -> the shared §26 math used by BOTH the customer-order ledger
           (core/subscribers) and the sourcing ledger (market/subscribers),
           plus the pricing engine (core/pricing).

Freight can come from a FreightRateCard (§21) — per-mode cards with fuel
surcharges and customs — falling back to the profile's flat per-kg when no
card matches. Customs/tax always folds INTO the logistics ledger bucket
(memo'd separately) so the entry taxonomy stays stable (§45).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.pricing import (
    LOGISTICS_NGN_PER_KG,
    LUXEEN_MARGIN_PCT,
    PAYMENT_COST_PCT,
)
from app.finance import models as fm

DEFAULT_CORRIDOR = "CN>NG"


def _corridor(origin: str | None, dest: str | None) -> str:
    return f"{(origin or 'CN').upper()}>{(dest or 'NG').upper()}"


def resolve_profile(
    db: Session,
    *,
    org_id: int | None = None,
    origin: str | None = None,
    dest: str | None = None,
    category: str | None = None,
) -> dict:
    """Most specific active profile wins; static constants are the fallback.

    Specificity score: org match (4) > platform (0); corridor match (2) >
    any (0); category match (1) > any (0). Ties break on priority, then id.
    """
    corridor = _corridor(origin, dest)
    profiles = (
        db.query(fm.WaterfallProfile)
        .filter(fm.WaterfallProfile.active == 1)
        .all()
    )

    best: tuple[int, int, int, fm.WaterfallProfile] | None = None
    for p in profiles:
        score = 0
        if p.org_id and p.org_id == org_id:
            score += 4
        elif p.org_id:  # another org's profile never applies
            continue
        if p.corridor:
            if p.corridor.upper() != corridor:
                continue
            score += 2
        if p.category:
            if (p.category or "").lower() != (category or "").lower():
                continue
            score += 1
        key = (score, p.priority, -p.id)
        if best is None or key > (best[0], best[1], -best[3].id):
            best = (score, p.priority, p.id, p)

    if best is None:
        return {
            "profile_id": None, "profile_name": "corridor defaults",
            "corridor": corridor, "category": category,
            "payment_cost_pct": PAYMENT_COST_PCT,
            "luxeen_margin_pct": LUXEEN_MARGIN_PCT,
            "operator_markup_pct": None,  # per-product override decides
            "logistics_per_kg_ngn": LOGISTICS_NGN_PER_KG,
            "tax_pct": 0.0,
        }

    p = best[3]
    return {
        "profile_id": p.id, "profile_name": p.name,
        "corridor": corridor, "category": category,
        "payment_cost_pct": p.payment_cost_pct if p.payment_cost_pct is not None else PAYMENT_COST_PCT,
        "luxeen_margin_pct": p.luxeen_margin_pct if p.luxeen_margin_pct is not None else LUXEEN_MARGIN_PCT,
        "operator_markup_pct": p.operator_markup_pct,
        "logistics_per_kg_ngn": p.logistics_per_kg_ngn if p.logistics_per_kg_ngn is not None else LOGISTICS_NGN_PER_KG,
        "tax_pct": p.tax_pct or 0.0,
    }


def compute_waterfall(
    *,
    supplier_ngn: float,
    weight_kg: float,
    qty: int = 1,
    profile: dict,
    rate_card: dict | None = None,
    round_to: float = 5.0,
) -> dict:
    """Shared waterfall math (§26). `rate_card` (from logistics.rates, already
    serialized) replaces the flat per-kg freight when provided.

    Returns component NGN amounts + the components memo map. Ledger shape is
    unchanged: supplier / logistics (freight + customs) / payment / luxeen —
    the operator share is derived as the remainder by callers.
    """
    supplier_ngn = float(supplier_ngn)
    weight_total = float(weight_kg) * max(int(qty), 1)

    if rate_card:
        freight = (
            float(rate_card.get("base_fixed_ngn") or 0.0)
            + float(rate_card.get("per_kg_ngn") or 0.0)
            * (1 + float(rate_card.get("fuel_surcharge_pct") or 0.0))
            * weight_total
        )
        if rate_card.get("min_charge_ngn"):
            freight = max(freight, float(rate_card["min_charge_ngn"]))
        customs = supplier_ngn * float(rate_card.get("customs_pct") or 0.0)
        card_label = f"{rate_card.get('name', 'rate card')} ({rate_card.get('mode', '')})"
    else:
        freight = profile["logistics_per_kg_ngn"] * weight_total
        customs = supplier_ngn * float(profile.get("tax_pct") or 0.0)
        card_label = "profile per-kg"

    logistics = freight + customs
    payment = (supplier_ngn + logistics) * profile["payment_cost_pct"]
    luxeen = supplier_ngn * profile["luxeen_margin_pct"]

    def _r(v: float) -> float:
        return round(v / round_to) * round_to if round_to else v

    return {
        "supplier_ngn": round(supplier_ngn, 2),
        "freight_ngn": round(freight, 2),
        "customs_ngn": round(customs, 2),
        "logistics_ngn": round(logistics, 2),
        "payment_ngn": round(payment, 2),
        "luxeen_ngn": round(luxeen, 2),
        "economics_basis": {
            "profile_id": profile.get("profile_id"),
            "profile_name": profile.get("profile_name"),
            "payment_cost_pct": profile["payment_cost_pct"],
            "luxeen_margin_pct": profile["luxeen_margin_pct"],
            "logistics_per_kg_ngn": profile["logistics_per_kg_ngn"],
            "tax_pct": profile.get("tax_pct", 0.0),
            "rate_card": card_label,
        },
        "_round": _r,
    }
