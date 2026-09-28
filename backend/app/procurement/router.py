"""Procurement / PO API (plan §21-22) incl. Stock Prophet reorder actions.

Read paths need `procurement:read`; everything that raises or moves money-
worth-of-goods needs `procurement:write` (owner/admin/luxeen_admin).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import AuthContext, require_auth, require_perm
from app.procurement import models as m
from app.procurement import service as svc

router = APIRouter(
    prefix="/procurement", tags=["procurement"],
    dependencies=[Depends(require_perm("procurement:read"))],
)


class PoLineIn(BaseModel):
    product_id: int
    qty: int


class PoIn(BaseModel):
    supplier_id: int
    lines: list[PoLineIn]
    expected_at: datetime | None = None
    note: str = ""


class ReceiptIn(BaseModel):
    receipts: dict[int, int]  # line_id -> qty
    warehouse_id: int | None = None  # §22 putaway target (default warehouse if omitted)


class FromSuggestionsIn(BaseModel):
    suggestion_ids: list[int] = []  # empty -> all open
    expected_at: datetime | None = None
    note: str = ""


def _po_or_404(db: Session, po_id: int, *, with_lines: bool = False):
    po = db.get(m.PurchaseOrder, po_id)
    if not po:
        raise HTTPException(404, "Purchase order not found")
    return svc.serialize_po(db, po, with_lines=with_lines)


# --------------------------------------------------------------------------
# Purchase orders
# --------------------------------------------------------------------------

@router.get("")
def list_pos(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(m.PurchaseOrder).order_by(m.PurchaseOrder.id.desc())
    if status:
        q = q.filter(m.PurchaseOrder.status == status)
    return [svc.serialize_po(db, po, with_lines=True) for po in q.all()]


@router.post("", status_code=201, dependencies=[Depends(require_perm("procurement:write"))])
def create_po(payload: PoIn, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_auth)):
    try:
        po = svc.create_po(db, supplier_id=payload.supplier_id,
                           lines=[l.model_dump() for l in payload.lines],
                           org_id=ctx.user.org_id, created_by=ctx.user.id,
                           expected_at=payload.expected_at, note=payload.note)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return _po_or_404(db, po.id, with_lines=True)


@router.get("/reorder-suggestions")
def list_suggestions(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(m.ReorderSuggestion).order_by(m.ReorderSuggestion.id.desc())
    if status:
        q = q.filter(m.ReorderSuggestion.status == status)
    return [svc.serialize_suggestion(db, s) for s in q.limit(200).all()]


@router.post("/reorder-suggestions/refresh")
def refresh_suggestions(db: Session = Depends(get_db)):
    """Materialise suggestions from the latest successful Stock Prophet run."""
    try:
        summary = svc.refresh_from_latest_run(db)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return summary


@router.post("/reorder-suggestions/create-po", status_code=201,
             dependencies=[Depends(require_perm("procurement:write"))])
def create_po_from_suggestions(payload: FromSuggestionsIn, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_auth)):
    try:
        pos = svc.po_from_suggestions(
            db, suggestion_ids=payload.suggestion_ids or None,
            org_id=ctx.user.org_id, created_by=ctx.user.id,
            expected_at=payload.expected_at, note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return [_po_or_404(db, po.id, with_lines=True) for po in pos]


@router.post("/reorder-suggestions/{suggestion_id}/dismiss")
def dismiss_suggestion(suggestion_id: int, db: Session = Depends(get_db)):
    s = db.get(m.ReorderSuggestion, suggestion_id)
    if not s:
        raise HTTPException(404, "Suggestion not found")
    if s.status != "open":
        raise HTTPException(400, f"Only open suggestions can be dismissed (this one is {s.status})")
    s.status = "dismissed"
    s.resolved_at = datetime.now(timezone.utc)
    db.commit()
    return svc.serialize_suggestion(db, s)


@router.get("/{po_id}")
def get_po(po_id: int, db: Session = Depends(get_db)):
    return _po_or_404(db, po_id, with_lines=True)


@router.post("/{po_id}/submit", dependencies=[Depends(require_perm("procurement:write"))])
def submit_po(po_id: int, db: Session = Depends(get_db)):
    po = db.get(m.PurchaseOrder, po_id)
    if not po:
        raise HTTPException(404, "Purchase order not found")
    try:
        svc.submit_po(db, po)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return _po_or_404(db, po_id, with_lines=True)


@router.post("/{po_id}/confirm", dependencies=[Depends(require_perm("procurement:write"))])
def confirm_po(po_id: int, db: Session = Depends(get_db)):
    po = db.get(m.PurchaseOrder, po_id)
    if not po:
        raise HTTPException(404, "Purchase order not found")
    try:
        svc.confirm_po(db, po)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return _po_or_404(db, po_id, with_lines=True)


@router.post("/{po_id}/receive", dependencies=[Depends(require_perm("procurement:write"))])
def receive_po(po_id: int, payload: ReceiptIn, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_auth)):
    po = db.get(m.PurchaseOrder, po_id)
    if not po:
        raise HTTPException(404, "Purchase order not found")
    try:
        svc.receive_po(db, po, payload.receipts, warehouse_id=payload.warehouse_id, received_by=ctx.user.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return _po_or_404(db, po_id, with_lines=True)


@router.post("/{po_id}/cancel", dependencies=[Depends(require_perm("procurement:write"))])
def cancel_po(po_id: int, db: Session = Depends(get_db)):
    po = db.get(m.PurchaseOrder, po_id)
    if not po:
        raise HTTPException(404, "Purchase order not found")
    try:
        svc.cancel_po(db, po)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return _po_or_404(db, po_id, with_lines=True)
