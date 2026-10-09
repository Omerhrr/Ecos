"""Freight rate resolution (plan §21 rate cards, §57 flexible economics).

Cards are data on a corridor: air vs sea vs express, fixed handling base,
per-kg headline rate, fuel surcharge, customs share of declared value and a
lead-time window. `resolve_rate` picks the best active card for a lane
(exact mode when given, otherwise the cheapest effective per-kg), so the
Marketstore can quote both modes and the waterfall can price with the same
card the buyer saw.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.logistics import models as lm


def serialize_card(c: lm.FreightRateCard) -> dict:
    return {
        "id": c.id, "org_id": c.org_id, "name": c.name, "mode": c.mode,
        "origin_country": c.origin_country, "dest_country": c.dest_country,
        "base_fixed_ngn": c.base_fixed_ngn, "per_kg_ngn": c.per_kg_ngn,
        "fuel_surcharge_pct": c.fuel_surcharge_pct, "customs_pct": c.customs_pct,
        "min_charge_ngn": c.min_charge_ngn,
        "lead_time_days_min": c.lead_time_days_min,
        "lead_time_days_max": c.lead_time_days_max,
        "active": bool(c.active), "priority": c.priority,
        "effective_per_kg_ngn": round(
            c.per_kg_ngn * (1 + (c.fuel_surcharge_pct or 0.0)), 2
        ),
    }


def _lane_cards(db: Session, *, origin: str, dest: str, org_id: int | None) -> list[lm.FreightRateCard]:
    q = (
        db.query(lm.FreightRateCard)
        .filter(
            lm.FreightRateCard.active == 1,
            lm.FreightRateCard.origin_country == (origin or "CN").upper(),
            lm.FreightRateCard.dest_country == (dest or "NG").upper(),
        )
    )
    cards = q.all()
    # org-specific cards win over platform cards at equal price
    cards.sort(key=lambda c: (-(c.org_id == org_id and org_id is not None), c.priority, c.id))
    return cards


def resolve_rate(
    db: Session,
    *,
    origin: str = "CN",
    dest: str = "NG",
    mode: str | None = None,
    org_id: int | None = None,
) -> dict | None:
    """Best card for a lane. Exact mode when given; otherwise AIR by default
    (the e-commerce standard — speed wins), falling back to the cheapest
    card on the lane when no air card exists. `lane_options` always exposes
    every mode so buyers can choose sea explicitly."""
    cards = _lane_cards(db, origin=origin, dest=dest, org_id=org_id)
    if not cards:
        return None
    if mode:
        exact = [c for c in cards if c.mode == mode]
        if exact:
            cards = exact
    else:
        air = [c for c in cards if c.mode == "air"]
        if air:
            cards = air
    best = min(cards, key=lambda c: c.per_kg_ngn * (1 + (c.fuel_surcharge_pct or 0.0)))
    return serialize_card(best)


def lane_options(
    db: Session,
    *,
    origin: str = "CN",
    dest: str = "NG",
    org_id: int | None = None,
) -> list[dict]:
    """One option per mode available on the lane (cheapest card per mode)."""
    cards = _lane_cards(db, origin=origin, dest=dest, org_id=org_id)
    by_mode: dict[str, lm.FreightRateCard] = {}
    for c in cards:
        eff = c.per_kg_ngn * (1 + (c.fuel_surcharge_pct or 0.0))
        cur = by_mode.get(c.mode)
        if cur is None or eff < cur.per_kg_ngn * (1 + (cur.fuel_surcharge_pct or 0.0)):
            by_mode[c.mode] = c
    return [serialize_card(c) for c in by_mode.values()]


def freight_cost(card: dict, *, declared_value_ngn: float, weight_total_kg: float) -> dict:
    """Freight + customs for a lane under one card (customs is a share of the
    declared supplier value — the memo keeps both visible, §45)."""
    freight = (
        float(card.get("base_fixed_ngn") or 0.0)
        + float(card.get("per_kg_ngn") or 0.0)
        * (1 + float(card.get("fuel_surcharge_pct") or 0.0))
        * float(weight_total_kg)
    )
    if card.get("min_charge_ngn"):
        freight = max(freight, float(card["min_charge_ngn"]))
    customs = float(declared_value_ngn) * float(card.get("customs_pct") or 0.0)
    return {"freight_ngn": round(freight, 2), "customs_ngn": round(customs, 2)}
