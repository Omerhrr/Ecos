"""FX conversion service (plan §46 — multi-currency).

Canonical directions are stored in `fx_rates` (1 base = rate quote);
anything not stored directly resolves through USD or NGN triangulation,
then falls back to the static pricing-engine table so the corridor never
breaks because a row is missing.

Money in the ledger keeps its capture currency — conversion here is for
DISPLAY (storefront currency toggle, USD pricing page) and for the FX
snapshot stamped onto orders at checkout.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.finance import models as fm

SUPPORTED = ["NGN", "USD", "CNY"]
# static fallback (kept in step with core.pricing.FX_RATES)
_STATIC = {
    ("CNY", "NGN"): 215.0, ("USD", "NGN"): 1530.0, ("CNY", "USD"): 0.14,
}


def get_rate(db: Session, base: str, quote: str) -> tuple[float, str]:
    """Return (rate, source). base == quote -> (1.0, 'identity').

    Resolution order: direct row -> inverse row -> triangulation through a
    third currency -> static fallback. Recursion-safe (pivots that equal
    base or quote are skipped).
    """
    base, quote = base.upper(), quote.upper()
    if base == quote:
        return 1.0, "identity"

    row = (
        db.query(fm.FxRate)
        .filter(fm.FxRate.base == base, fm.FxRate.quote == quote)
        .first()
    )
    if row:
        return float(row.rate), row.source or "manual"

    inverse = (
        db.query(fm.FxRate)
        .filter(fm.FxRate.base == quote, fm.FxRate.quote == base)
        .first()
    )
    if inverse and inverse.rate:
        return round(1.0 / float(inverse.rate), 10), f"inverse:{inverse.source or 'manual'}"

    for pivot in ("USD", "NGN", "CNY"):
        if pivot in (base, quote):
            continue
        try:
            r1, s1 = get_rate(db, base, pivot)
            r2, s2 = get_rate(db, pivot, quote)
        except ValueError:
            continue
        if r1 and r2:
            return r1 * r2, f"triangulated:{s1}+{s2}"

    static = _STATIC.get((base, quote)) or (
        round(1.0 / _STATIC[(quote, base)], 10) if (quote, base) in _STATIC else None
    )
    if static:
        return static, "static-fallback"
    raise ValueError(f"No FX rate available for {base}->{quote}")


def convert(db: Session, amount: float, base: str, quote: str) -> dict:
    rate, source = get_rate(db, base, quote)
    return {"amount": round(amount * rate, 2), "rate": rate,
            "from": base.upper(), "to": quote.upper(), "source": source}


def set_rate(db: Session, base: str, quote: str, rate: float, *,
             user_id: int | None = None, source: str = "manual") -> fm.FxRate:
    base, quote = base.upper(), quote.upper()
    if base == quote:
        raise ValueError("base and quote must differ")
    if rate <= 0:
        raise ValueError("rate must be positive")
    row = db.query(fm.FxRate).filter(fm.FxRate.base == base, fm.FxRate.quote == quote).first()
    if row is None:
        row = fm.FxRate(base=base, quote=quote, rate=rate)
        db.add(row)
    row.rate = rate
    row.source = source
    row.updated_by = user_id
    db.flush()
    return row


def all_rates(db: Session) -> list[dict]:
    rows = db.query(fm.FxRate).order_by(fm.FxRate.base, fm.FxRate.quote).all()
    return [
        {
            "base": r.base, "quote": r.quote, "rate": r.rate,
            "source": r.source, "updated_by": r.updated_by,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


def seed_rates(db: Session) -> None:
    """Idempotent seed of the corridor's canonical rates."""
    defaults = [
        ("CNY", "NGN", 215.0), ("USD", "NGN", 1530.0), ("CNY", "USD", 0.14),
    ]
    for base, quote, rate in defaults:
        existing = db.query(fm.FxRate).filter(fm.FxRate.base == base, fm.FxRate.quote == quote).first()
        if existing is None:
            db.add(fm.FxRate(base=base, quote=quote, rate=rate, source="seed"))
    db.flush()
