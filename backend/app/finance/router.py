from fastapi import APIRouter, Depends
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_perm
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
