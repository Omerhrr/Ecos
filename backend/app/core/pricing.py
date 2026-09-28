"""Pricing engine (plan §12).

Ecos treats pricing as a dedicated domain. The initial corridor uses a
transparent waterfall from supplier cost (CNY) to the operator-facing
Ecos price (NGN):

    Supplier Cost (CNY)
      -> FX conversion
      + International logistics (per kg)
      + Payment cost
      + Luxeen economics (margin)
      + Operator markup (configurable, default 10%)
      = Ecos Price (NGN, rounded to nearest 5)

The function returns the full breakdown so the same computation can later
support country markups, volume pricing, promotions, dynamic pricing, and
additional currencies without changing callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Config-driven rates — swap for a live FX service / rate tables later (§46).
FX_RATES: dict[str, dict[str, float]] = {
    "CNY": {"NGN": 215.0, "USD": 0.14},
    "USD": {"NGN": 1530.0},
}

LOGISTICS_NGN_PER_KG = 3800.0  # intl freight + customs + last-mile, per kg
PAYMENT_COST_PCT = 0.015
LUXEEN_MARGIN_PCT = 0.08
DEFAULT_MARKUP_PCT = 0.10  # plan §12: Supplier Price × 1.10 baseline
DEFAULT_WEIGHT_KG = 0.5
ROUND_TO = 5.0


@dataclass
class PriceBreakdown:
    supplier_cost_original: float
    currency_original: str
    fx_rate: float
    supplier_cost_ngn: float
    logistics_ngn: float
    payment_cost_ngn: float
    luxeen_margin_ngn: float
    operator_margin_ngn: float
    ecos_price_ngn: float = 0.0
    components: dict[str, float] = field(default_factory=dict)


def price_product(
    supplier_cost: float,
    currency: str = "CNY",
    weight_kg: float | None = None,
    markup_pct: float | None = None,
    target_currency: str = "NGN",
) -> PriceBreakdown:
    """Compute the operator-facing Ecos price plus the full cost waterfall."""
    if currency == target_currency:
        rate = 1.0
    else:
        rate = FX_RATES[currency][target_currency]

    cost = supplier_cost * rate
    logistics = (weight_kg if weight_kg is not None else DEFAULT_WEIGHT_KG) * LOGISTICS_NGN_PER_KG
    payment = (cost + logistics) * PAYMENT_COST_PCT
    luxeen = cost * LUXEEN_MARGIN_PCT
    markup = markup_pct if markup_pct is not None else DEFAULT_MARKUP_PCT
    operator_margin = cost * markup

    base = cost + logistics + payment + luxeen
    price = _round_to(base + operator_margin, ROUND_TO)

    return PriceBreakdown(
        supplier_cost_original=supplier_cost,
        currency_original=currency,
        fx_rate=rate,
        supplier_cost_ngn=round(cost, 2),
        logistics_ngn=round(logistics, 2),
        payment_cost_ngn=round(payment, 2),
        luxeen_margin_ngn=round(luxeen, 2),
        operator_margin_ngn=round(operator_margin, 2),
        ecos_price_ngn=price,
        components={
            "supplier_cost": round(cost, 2),
            "logistics": round(logistics, 2),
            "payment_cost": round(payment, 2),
            "luxeen_margin": round(luxeen, 2),
            "operator_margin": round(operator_margin, 2),
        },
    )


def _round_to(value: float, step: float) -> float:
    return round(value / step) * step
