"""§21/§57 economics defaults — idempotent, runs on every boot.

Seeds the platform waterfall profile (matching the historical constants so
behaviour is unchanged until a human changes it) and the corridor's freight
rate cards (air vs sea on CN→NG). Existing rows are never overwritten —
these are commercial settings, so once a human edits them the seed stands
down.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.finance import models as fm
from app.logistics import models as lm

PLATFORM_PROFILE = {
    "name": "Corridor CN→NG baseline (platform)",
    "org_id": None,
    "corridor": "CN>NG",
    "category": "",
    "payment_cost_pct": 0.015,
    "luxeen_margin_pct": 0.08,
    "operator_markup_pct": 0.10,
    "logistics_per_kg_ngn": 3800.0,
    "tax_pct": 0.0,
    "priority": 0,
}

RATE_CARDS = [
    {
        "name": "Air Express CN→NG",
        "mode": "air", "origin_country": "CN", "dest_country": "NG",
        "base_fixed_ngn": 1500.0, "per_kg_ngn": 4200.0,
        "fuel_surcharge_pct": 0.10, "customs_pct": 0.05,
        "min_charge_ngn": 6000.0,
        "lead_time_days_min": 7, "lead_time_days_max": 12,
        "priority": 10,
    },
    {
        "name": "Sea Freight CN→NG",
        "mode": "sea", "origin_country": "CN", "dest_country": "NG",
        "base_fixed_ngn": 3500.0, "per_kg_ngn": 2200.0,
        "fuel_surcharge_pct": 0.05, "customs_pct": 0.08,
        "min_charge_ngn": 12000.0,
        "lead_time_days_min": 35, "lead_time_days_max": 50,
        "priority": 5,
    },
]


def seed_economics_if_missing(db: Session) -> None:
    created: list[str] = []

    if not db.query(fm.WaterfallProfile).first():
        db.add(fm.WaterfallProfile(**PLATFORM_PROFILE))
        created.append("waterfall_profile")

    have_cards = db.query(lm.FreightRateCard).first()
    if not have_cards:
        for card in RATE_CARDS:
            db.add(lm.FreightRateCard(**card))
        created.append("freight_rate_cards")

    if created:
        db.flush()
        print(f"[seed] economics defaults created: {', '.join(created)}")
