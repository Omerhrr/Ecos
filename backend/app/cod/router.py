"""COD remittance register API (plan §24 — courier remittance + reconciliation).

Open a register per courier, auto-attach every collected-but-unreconciled
COD payment for that carrier, submit the courier's remittance, then
reconcile line-by-line. Reconciliation stamps payments `reconciled`, writes
a `cod_variance` ledger true-up when the cash doesn't add up, and publishes
`cod.remittance_reconciled` so the automation engine (§41) and notification
flows can react.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import AuthContext, require_auth, require_perm
from app.core.events import publish
from app.finance import models as fm
from app.logistics import models as lm
from app.orders import models as om
from app.payments import models as pm
from app.storefront import models as stm

from . import models as m

router = APIRouter(prefix="/cod", tags=["cod"])


class RegisterIn(BaseModel):
    carrier: str = Field(min_length=1, max_length=120)
    note: str = ""


class SubmitIn(BaseModel):
    remitted_amount: float = Field(ge=0)
    reference: str = ""


class CountLineIn(BaseModel):
    line_id: int
    counted_amount: float = Field(ge=0)


class ReconcileIn(BaseModel):
    counts: list[CountLineIn] = []


def _register_dict(db: Session, r: m.CodRemittance, *, with_lines: bool = False) -> dict:
    lines = db.query(m.CodRemittanceLine).filter(m.CodRemittanceLine.remittance_id == r.id).all()
    out = {
        "id": r.id, "register_code": r.register_code, "org_id": r.org_id,
        "carrier": r.carrier, "status": r.status, "currency": r.currency,
        "expected_amount": round(r.expected_amount, 2),
        "remitted_amount": round(r.remitted_amount, 2),
        "counted_amount": round(r.counted_amount, 2),
        "variance_amount": round(r.variance_amount, 2),
        "reference": r.reference, "note": r.note,
        "line_count": len(lines),
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "remitted_at": r.remitted_at.isoformat() if r.remitted_at else None,
        "reconciled_at": r.reconciled_at.isoformat() if r.reconciled_at else None,
    }
    if with_lines:
        out["lines"] = [_line_dict(db, l) for l in lines]
    return out


def _line_dict(db: Session, l: m.CodRemittanceLine) -> dict:
    order = db.get(om.Order, l.order_id)
    payment = db.get(pm.Payment, l.payment_id)
    return {
        "id": l.id, "payment_id": l.payment_id, "order_id": l.order_id,
        "order_number": f"#{l.order_id}",
        "shipment_id": l.shipment_id,
        "expected_amount": round(l.expected_amount, 2),
        "counted_amount": round(l.counted_amount, 2),
        "collected_at": payment.collected_at.isoformat() if payment and payment.collected_at else None,
    }


def _get_scoped(ctx: AuthContext, register_id: int, db: Session) -> m.CodRemittance:
    r = db.get(m.CodRemittance, register_id)
    if r is None or (not ctx.is_platform and r.org_id != ctx.user.org_id):
        raise HTTPException(404, "Register not found")
    return r


@router.get("/registers", dependencies=[Depends(require_perm("finance:read"))])
def list_registers(status: str | None = None, db: Session = Depends(get_db),
                   ctx: AuthContext = Depends(require_auth)):
    q = db.query(m.CodRemittance).order_by(m.CodRemittance.id.desc())
    if not ctx.is_platform:
        q = q.filter(m.CodRemittance.org_id == ctx.user.org_id)
    if status:
        q = q.filter(m.CodRemittance.status == status)
    return [_register_dict(db, r) for r in q.limit(200).all()]


@router.post("/registers", status_code=201, dependencies=[Depends(require_perm("finance:write"))])
def open_register(payload: RegisterIn, db: Session = Depends(get_db),
                  ctx: AuthContext = Depends(require_auth)):
    """Open a remittance register for a courier and auto-attach every
    collected-but-unreconciled COD payment carried by that courier."""
    carrier = payload.carrier.strip()
    org_id = ctx.user.org_id

    # eligible: COD + collected + not yet reconciled + not in an active register
    # + carried by this courier (via the order's shipment)
    attached = (
        db.query(pm.Payment.id)
        .join(m.CodRemittanceLine, m.CodRemittanceLine.payment_id == pm.Payment.id)
        .join(m.CodRemittance, m.CodRemittance.id == m.CodRemittanceLine.remittance_id)
        .filter(m.CodRemittance.status.in_(["draft", "remitted", "reconciled"]))
    ).scalar_subquery()

    rows = (
        db.query(pm.Payment, om.Order, lm.Shipment)
        .join(om.Order, om.Order.id == pm.Payment.order_id)
        .join(stm.Store, stm.Store.id == om.Order.store_id)
        .join(lm.Shipment, lm.Shipment.order_id == om.Order.id)
        .filter(
            pm.Payment.method == "cod",
            pm.Payment.status == "paid",
            pm.Payment.reconciled == 0,
            ~pm.Payment.id.in_(attached),
            lm.Shipment.carrier == carrier,
        )
        .order_by(pm.Payment.id)
        .all()
    )
    if not ctx.is_platform:
        rows = [r for r in rows if _order_org_id(db, r[1]) == org_id]
    if not rows:
        raise HTTPException(404, f"No unreconciled COD collections found for carrier '{carrier}'")

    reg = m.CodRemittance(
        register_code="pending", org_id=org_id, carrier=carrier,
        currency="NGN", note=payload.note, created_by=ctx.user.id,
    )
    db.add(reg)
    db.flush()
    reg.register_code = f"CODR-{reg.id:05d}"

    expected_total = 0.0
    for payment, order, shipment in rows:
        db.add(m.CodRemittanceLine(
            remittance_id=reg.id, payment_id=payment.id, order_id=order.id,
            shipment_id=shipment.id, expected_amount=payment.amount,
            counted_amount=0.0,
        ))
        expected_total += payment.amount
    reg.expected_amount = round(expected_total, 2)

    publish(db, "cod.register_opened", {
        "register_id": reg.id, "register_code": reg.register_code,
        "carrier": carrier, "expected_amount": reg.expected_amount,
        "line_count": len(rows),
    })
    db.commit()
    return _register_dict(db, reg, with_lines=True)


def _order_org_id(db: Session, order: om.Order) -> int | None:
    store = db.get(stm.Store, order.store_id)
    return store.org_id if store else None


@router.get("/registers/{register_id}", dependencies=[Depends(require_perm("finance:read"))])
def get_register(register_id: int, db: Session = Depends(get_db),
                 ctx: AuthContext = Depends(require_auth)):
    return _register_dict(db, _get_scoped(ctx, register_id, db), with_lines=True)


@router.post("/registers/{register_id}/submit", dependencies=[Depends(require_perm("finance:write"))])
def submit_register(register_id: int, payload: SubmitIn, db: Session = Depends(get_db),
                    ctx: AuthContext = Depends(require_auth)):
    """The courier handed over cash — record the remittance against the register."""
    r = _get_scoped(ctx, register_id, db)
    if r.status != "draft":
        raise HTTPException(400, f"Cannot submit a register in status {r.status}")
    r.status = "remitted"
    r.remitted_amount = round(payload.remitted_amount, 2)
    r.reference = payload.reference.strip() or r.reference
    r.remitted_at = datetime.now(timezone.utc)
    db.commit()
    return _register_dict(db, r, with_lines=True)


@router.post("/registers/{register_id}/reconcile", dependencies=[Depends(require_perm("finance:write"))])
def reconcile_register(register_id: int, payload: ReconcileIn, db: Session = Depends(get_db),
                       ctx: AuthContext = Depends(require_auth)):
    """Count the cash line-by-line. Zero variance → clean close; any variance
    becomes a signed `cod_variance` ledger true-up (party: logistics) so the
    ledger still ties to reality (§26/§45). Payments get their reconciled flag."""
    r = _get_scoped(ctx, register_id, db)
    if r.status != "remitted":
        raise HTTPException(400, f"Reconcile expects a 'remitted' register (current: {r.status})")

    counts = {c.line_id: c.counted_amount for c in payload.counts}
    lines = db.query(m.CodRemittanceLine).filter(m.CodRemittanceLine.remittance_id == r.id).all()

    counted_total = 0.0
    for l in lines:
        counted = counts.get(l.id, l.expected_amount)  # uncounted lines assumed intact
        l.counted_amount = round(float(counted), 2)
        counted_total += l.counted_amount
        payment = db.get(pm.Payment, l.payment_id)
        if payment:
            payment.reconciled = 1

    r.status = "reconciled"
    r.counted_amount = round(counted_total, 2)
    r.variance_amount = round(counted_total - r.expected_amount, 2)
    r.reconciled_at = datetime.now(timezone.utc)

    if abs(r.variance_amount) >= 0.01:
        # Double-entry true-up (§26/§45): the collected-cash reality is
        # corrected against the courier (shortage = outflow), and the
        # operator's margin absorbs the difference so the ledger still
        # sums to zero — an imbalance flag stays meaningful for real bugs.
        db.add(fm.LedgerEntry(
            order_id=None, entry_type="cod_variance", party="logistics",
            amount=r.variance_amount, currency=r.currency,
            memo=(f"COD remittance {r.register_code} ({r.carrier}): counted "
                  f"{r.counted_amount:,.2f} vs expected {r.expected_amount:,.2f}"),
        ))
        db.add(fm.LedgerEntry(
            order_id=None, entry_type="cod_variance", party="operator",
            amount=-r.variance_amount, currency=r.currency,
            memo=(f"COD remittance {r.register_code}: variance absorbed by "
                  f"operator margin"),
        ))

    publish(db, "cod.remittance_reconciled", {
        "register_id": r.id, "register_code": r.register_code,
        "carrier": r.carrier, "expected_amount": r.expected_amount,
        "counted_amount": r.counted_amount, "variance_amount": r.variance_amount,
    })
    db.commit()
    return _register_dict(db, r, with_lines=True)


@router.post("/registers/{register_id}/cancel", dependencies=[Depends(require_perm("finance:write"))])
def cancel_register(register_id: int, db: Session = Depends(get_db),
                    ctx: AuthContext = Depends(require_auth)):
    r = _get_scoped(ctx, register_id, db)
    if "cancelled" not in m.REGISTER_TRANSITIONS.get(r.status, []):
        raise HTTPException(400, f"Cannot cancel a register in status {r.status}")
    r.status = "cancelled"
    db.commit()
    return _register_dict(db, r)


@router.get("/summary", dependencies=[Depends(require_perm("finance:read"))])
def cod_summary(db: Session = Depends(get_db), ctx: AuthContext = Depends(require_auth)):
    """Custody snapshot: collected cash still held by each courier (§24)."""
    attached = (
        db.query(m.CodRemittanceLine.payment_id)
        .join(m.CodRemittance, m.CodRemittance.id == m.CodRemittanceLine.remittance_id)
        .filter(m.CodRemittance.status.in_(["draft", "remitted", "reconciled"]))
    )
    rows = (
        db.query(lm.Shipment.carrier, pm.Payment)
        .join(om.Order, om.Order.id == pm.Payment.order_id)
        .join(stm.Store, stm.Store.id == om.Order.store_id)
        .join(lm.Shipment, lm.Shipment.order_id == om.Order.id)
        .filter(pm.Payment.method == "cod", pm.Payment.status == "paid",
                pm.Payment.reconciled == 0, ~pm.Payment.id.in_(attached.scalar_subquery()))
        .all()
    )
    if not ctx.is_platform:
        rows = [
            (carrier, payment) for carrier, payment in rows
            if (_order_org_id(db, db.get(om.Order, payment.order_id)) == ctx.user.org_id)
        ]

    by_carrier: dict[str, dict] = {}
    for carrier, payment in rows:
        bucket = by_carrier.setdefault(carrier, {
            "carrier": carrier, "outstanding_amount": 0.0, "outstanding_count": 0,
        })
        bucket["outstanding_amount"] += payment.amount
        bucket["outstanding_count"] += 1

    regs = db.query(m.CodRemittance).filter(m.CodRemittance.status == "reconciled").all()
    if not ctx.is_platform:
        regs = [r for r in regs if r.org_id == ctx.user.org_id]
    last_reconciled = max((r.reconciled_at for r in regs if r.reconciled_at), default=None)

    return {
        "outstanding_by_carrier": sorted(
            by_carrier.values(), key=lambda b: -b["outstanding_amount"]),
        "outstanding_total": round(sum(b["outstanding_amount"] for b in by_carrier.values()), 2),
        "registers_reconciled": len(regs),
        "last_reconciled_at": last_reconciled.isoformat() if last_reconciled else None,
    }
