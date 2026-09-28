from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import AuthContext, require_perm
from app.core.events import publish
from app.finance import fx
from app.finance import models as m

router = APIRouter(
    prefix="/finance", tags=["finance"],
    dependencies=[Depends(require_perm("finance:read"))],
)


@router.get("/ledger")
def ledger(order_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(m.LedgerEntry).order_by(m.LedgerEntry.id.desc())
    if order_id:
        q = q.filter(m.LedgerEntry.order_id == order_id)
    entries = [
        {
            "id": e.id, "order_id": e.order_id, "entry_type": e.entry_type,
            "party": e.party, "amount": e.amount, "currency": e.currency,
            "memo": e.memo, "created_at": e.created_at.isoformat(),
        }
        for e in q.limit(500).all()
    ]

    by_type = dict(
        db.query(m.LedgerEntry.entry_type, sa_func.sum(m.LedgerEntry.amount))
        .group_by(m.LedgerEntry.entry_type)
        .all()
    )
    return {"entries": entries, "totals_by_type": by_type}


# ------------------------------------------------------------------ §46 FX

class FxRateIn(BaseModel):
    base: str = Field(min_length=3, max_length=3)
    quote: str = Field(min_length=3, max_length=3)
    rate: float = Field(gt=0)


@router.get("/fx")
def list_fx(db: Session = Depends(get_db)):
    """The corridor's rate table (§46)."""
    return {"rates": fx.all_rates(db), "supported": fx.SUPPORTED}


@router.post("/fx", dependencies=[Depends(require_perm("finance:write"))])
def upsert_fx(
    payload: FxRateIn,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_perm("finance:write")),
):
    try:
        row = fx.set_rate(db, payload.base, payload.quote, payload.rate, user_id=ctx.user.id)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    publish(db, "finance.fx_rate_updated", {
        "base": row.base, "quote": row.quote, "rate": row.rate, "by": ctx.user.id,
    })
    db.commit()
    return {"base": row.base, "quote": row.quote, "rate": row.rate,
            "source": row.source, "updated_at": row.updated_at.isoformat() if row.updated_at else None}


@router.get("/fx/convert")
def convert_fx(amount: float, base: str = "NGN", quote: str = "USD", db: Session = Depends(get_db)):
    try:
        return fx.convert(db, amount, base, quote)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
