from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.audit import service as audit_service
from app.core.database import get_db
from app.core.deps import AuthContext, require_perm
from app.core.events import publish
from app.finance import economics
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
    request: Request,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_perm("finance:write")),
):
    existing = db.query(m.FxRate).filter(
        m.FxRate.base == payload.base.upper(), m.FxRate.quote == payload.quote.upper()
    ).first()
    before = {"base": existing.base, "quote": existing.quote, "rate": existing.rate} if existing else None
    try:
        row = fx.set_rate(db, payload.base, payload.quote, payload.rate, user_id=ctx.user.id)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    publish(db, "finance.fx_rate_updated", {
        "base": row.base, "quote": row.quote, "rate": row.rate, "by": ctx.user.id,
    })
    audit_service.record(
        db, ctx=ctx, request=request,
        action="finance.fx_rate_updated", entity_type="fx_rate",
        entity_id=f"{row.base}/{row.quote}", before=before,
        after={"base": row.base, "quote": row.quote, "rate": row.rate},
        auth_context="finance:write",
    )
    db.commit()
    return {"base": row.base, "quote": row.quote, "rate": row.rate,
            "source": row.source, "updated_at": row.updated_at.isoformat() if row.updated_at else None}


@router.get("/fx/convert")
def convert_fx(amount: float, base: str = "NGN", quote: str = "USD", db: Session = Depends(get_db)):
    try:
        return fx.convert(db, amount, base, quote)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


# ---------------------------------------------------- §57 economics profiles

def serialize_profile(p: m.WaterfallProfile) -> dict:
    return {
        "id": p.id, "org_id": p.org_id, "name": p.name,
        "corridor": p.corridor, "category": p.category,
        "payment_cost_pct": p.payment_cost_pct,
        "luxeen_margin_pct": p.luxeen_margin_pct,
        "operator_markup_pct": p.operator_markup_pct,
        "logistics_per_kg_ngn": p.logistics_per_kg_ngn,
        "tax_pct": p.tax_pct,
        "active": bool(p.active), "priority": p.priority,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


class ProfileIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    org_id: int | None = None
    corridor: str = ""     # "" = any lane; "CN>NG" style
    category: str = ""     # "" = any category
    payment_cost_pct: float | None = Field(default=None, ge=0, le=0.5)
    luxeen_margin_pct: float | None = Field(default=None, ge=0, le=1)
    operator_markup_pct: float | None = Field(default=None, ge=0, le=5)
    logistics_per_kg_ngn: float | None = Field(default=None, ge=0)
    tax_pct: float | None = Field(default=None, ge=0, le=1)
    active: bool = True
    priority: int = 0


@router.get("/profiles")
def list_profiles(db: Session = Depends(get_db)):
    profiles = db.query(m.WaterfallProfile).order_by(
        m.WaterfallProfile.priority.desc(), m.WaterfallProfile.id
    ).all()
    return {
        "profiles": [serialize_profile(p) for p in profiles],
        "defaults": {
            "payment_cost_pct": economics.PAYMENT_COST_PCT,
            "luxeen_margin_pct": economics.LUXEEN_MARGIN_PCT,
            "logistics_per_kg_ngn": economics.LOGISTICS_NGN_PER_KG,
        },
    }


@router.post("/profiles", status_code=201, dependencies=[Depends(require_perm("finance:write"))])
def create_profile(
    payload: ProfileIn, request: Request,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_perm("finance:write")),
):
    p = m.WaterfallProfile(
        org_id=payload.org_id if ctx.is_platform else (ctx.org.id if ctx.org else None),
        name=payload.name.strip(),
        corridor=payload.corridor.strip().upper().replace("→", ">"),
        category=payload.category.strip().lower(),
        payment_cost_pct=payload.payment_cost_pct,
        luxeen_margin_pct=payload.luxeen_margin_pct,
        operator_markup_pct=payload.operator_markup_pct,
        logistics_per_kg_ngn=payload.logistics_per_kg_ngn,
        tax_pct=payload.tax_pct,
        active=1 if payload.active else 0,
        priority=payload.priority,
    )
    db.add(p)
    db.flush()
    audit_service.record(
        db, ctx=ctx, request=request,
        action="finance.profile_created", entity_type="waterfall_profile",
        entity_id=p.id, after=serialize_profile(p), auth_context="finance:write",
    )
    db.commit()
    return serialize_profile(p)


@router.patch("/profiles/{profile_id}", dependencies=[Depends(require_perm("finance:write"))])
def patch_profile(
    profile_id: int, payload: ProfileIn, request: Request,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_perm("finance:write")),
):
    p = db.get(m.WaterfallProfile, profile_id)
    if not p:
        raise HTTPException(404, "Profile not found")
    before = serialize_profile(p)
    data = payload.model_dump(exclude_none=True)
    for k, v in data.items():
        if k == "active":
            p.active = 1 if v else 0
        elif k == "corridor":
            p.corridor = str(v).strip().upper().replace("→", ">")
        elif k == "category":
            p.category = str(v).strip().lower()
        else:
            setattr(p, k, v)
    audit_service.record(
        db, ctx=ctx, request=request,
        action="finance.profile_updated", entity_type="waterfall_profile",
        entity_id=p.id, before=before, after=serialize_profile(p),
        auth_context="finance:write",
    )
    db.commit()
    return serialize_profile(p)


class PreviewIn(BaseModel):
    supplier_cost: float = Field(gt=0)
    currency: str = "CNY"
    weight_kg: float = Field(default=0.5, gt=0)
    qty: int = Field(default=1, ge=1)
    org_id: int | None = None
    origin: str = "CN"
    dest: str = "NG"
    category: str | None = None
    markup_pct: float | None = None


@router.post("/profiles/preview")
def preview_waterfall(payload: PreviewIn, db: Session = Depends(get_db)):
    """Simulate the §12/§26/§57 waterfall under the resolved profile + lane."""
    conv = fx.convert(db, payload.supplier_cost, payload.currency, "NGN")
    supplier_ngn = float(conv["amount"])
    profile = economics.resolve_profile(
        db, org_id=payload.org_id, origin=payload.origin, dest=payload.dest,
        category=payload.category,
    )
    from app.logistics import rates as rates_service

    card = rates_service.resolve_rate(
        db, origin=payload.origin, dest=payload.dest, org_id=payload.org_id
    )
    wf = economics.compute_waterfall(
        supplier_ngn=supplier_ngn, weight_kg=payload.weight_kg, qty=payload.qty,
        profile=profile, rate_card=card,
    )
    total = supplier_ngn * payload.qty + wf["logistics_ngn"] + wf["payment_ngn"] + wf["luxeen_ngn"]
    markup = payload.markup_pct if payload.markup_pct is not None else profile.get("operator_markup_pct")
    ecos_price = round((total + (markup if markup is not None else 0.10) * supplier_ngn * payload.qty) / 5) * 5
    return {
        "fx": conv, "profile": profile, "rate_card": card,
        "waterfall": {k: v for k, v in wf.items() if k != "_round"},
        "supply_total_ngn": round(total, 2),
        "ecos_price_ngn": ecos_price,
    }
