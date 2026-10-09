"""Market router — three surfaces, one domain:

  /market/products, /market/sourcing-orders      OPERATOR (buy side, §11)
  /market/portal/*                                SUPPLIER (upload + fulfil, §8)
  /market/admin/*                                 LUXEEN (review gate, §8)

Isolation (§9): operator payloads carry no supplier identity; supplier
payloads carry no buyer identity. The review gate and supplier provisioning
are platform-staff only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import AuthContext, require_auth, require_perm, require_role
from app.core.events import publish
from app.agm import models as agm_m
from app.core.security import hash_password
from app.identity import models as im
from app.market import models as m
from app.market import service as svc
from app.supply import models as sm

router = APIRouter(prefix="/market", tags=["market"])


# ---------------------------------------------------------------------------
# Pydantic payloads
# ---------------------------------------------------------------------------

class SupplierProductIn(BaseModel):
    title: str
    description: str = ""
    category: str = "general"
    industry: str = ""
    cost_price: float = Field(gt=0)
    currency: str = "CNY"
    weight_kg: float = Field(default=0.5, gt=0)
    moq: int = Field(default=1, ge=1)
    images: list[str] = []
    specs: dict = {}


class SupplierProductPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    category: str | None = None
    industry: str | None = None
    cost_price: float | None = Field(default=None, gt=0)
    currency: str | None = None
    weight_kg: float | None = Field(default=None, gt=0)
    moq: int | None = Field(default=None, ge=1)
    images: list[str] | None = None
    specs: dict | None = None


class ReviewIn(BaseModel):
    decision: str  # approve | reject
    notes: str = ""


class SupplierOrgIn(BaseModel):
    company: str
    contact_name: str
    email: str
    password: str
    city: str = ""
    country: str = "CN"


class SourcingOrderIn(BaseModel):
    supplier_product_id: int
    qty: int = Field(ge=1)
    agent_org_id: int | None = None
    dest_name: str = ""
    dest_phone: str = ""
    dest_address: str = ""
    dest_city: str = ""
    dest_country: str = "NG"
    note: str = ""


class PayIn(BaseModel):
    method: str = "wallet"
    reference: str = ""


class TrackingIn(BaseModel):
    code: str
    location: str = ""
    description: str = ""


# ---------------------------------------------------------------------------
# OPERATOR — Marketstore (buy side). Isolation: serialized via serialize_listing.
# ---------------------------------------------------------------------------

@router.get("/products")
def market_products(
    category: str | None = None,
    industry: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_perm("market:read")),
):
    query = db.query(m.SupplierProduct).filter(m.SupplierProduct.status == "published")
    if category:
        query = query.filter(m.SupplierProduct.category == category)
    if industry:
        query = query.filter(m.SupplierProduct.industry == industry)
    if q:
        query = query.filter(m.SupplierProduct.title.ilike(f"%{q}%"))
    rows = query.order_by(m.SupplierProduct.id.desc()).all()
    return [svc.serialize_listing(db, sp) for sp in rows]


@router.get("/products/{sp_id}")
def market_product(sp_id: int, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_perm("market:read"))):
    sp = db.get(m.SupplierProduct, sp_id)
    if sp is None or sp.status != "published":
        raise HTTPException(404, "Product not found on the Marketstore")
    return svc.serialize_listing(db, sp)


@router.get("/meta")
def market_meta(ctx: AuthContext = Depends(require_auth)):
    return {"categories": ["electronics", "home-appliances", "accessories", "beauty", "fashion", "general"],
            "industries": ["consumer-electronics", "home-living", "beauty", "fashion", "tools", "toys", "general"]}


@router.post("/sourcing-orders", status_code=201)
def create_sourcing_order(
    payload: SourcingOrderIn,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_perm("market:buy")),
):
    # agent link check: operators can only route to agents linked to them
    if payload.agent_org_id:
        link = (
            db.query(agm_m.AgentLink)
            .filter(
                agm_m.AgentLink.agent_org_id == payload.agent_org_id,
                agm_m.AgentLink.vendor_org_id == ctx.user.org_id,
                agm_m.AgentLink.status == "active",
            )
            .first()
        )
        if link is None:
            raise HTTPException(400, "That agent is not linked to your organization — add them first under Agents")
    try:
        so = svc.create_sourcing_order(
            db, supplier_product_id=payload.supplier_product_id, org_id=ctx.user.org_id,
            qty=payload.qty, created_by=ctx.user.id, agent_org_id=payload.agent_org_id,
            dest_name=payload.dest_name, dest_phone=payload.dest_phone,
            dest_address=payload.dest_address, dest_city=payload.dest_city,
            dest_country=payload.dest_country, note=payload.note,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return svc.serialize_sourcing_operator(db, so, with_events=True)


@router.get("/sourcing-orders")
def my_sourcing_orders(
    status: str | None = None,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_perm("market:read")),
):
    q = db.query(m.SourcingOrder).filter(m.SourcingOrder.org_id == ctx.user.org_id)
    if status:
        q = q.filter(m.SourcingOrder.status == status)
    rows = q.order_by(m.SourcingOrder.id.desc()).limit(200).all()
    return [svc.serialize_sourcing_operator(db, so, with_events=True) for so in rows]


@router.post("/sourcing-orders/{so_id}/pay")
def pay_sourcing_order(
    so_id: int, payload: PayIn,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_perm("market:buy")),
):
    so = _own_sourcing(db, so_id, ctx)
    try:
        svc.pay_sourcing_order(db, so, method=payload.method, reference=payload.reference, actor=ctx.user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return svc.serialize_sourcing_operator(db, so, with_events=True)


@router.post("/sourcing-orders/{so_id}/cancel")
def cancel_sourcing_order(
    so_id: int, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_perm("market:buy"))
):
    so = _own_sourcing(db, so_id, ctx)
    try:
        svc.cancel_sourcing_order(db, so)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return svc.serialize_sourcing_operator(db, so, with_events=True)


@router.post("/sourcing-orders/{so_id}/receive")
def receive_sourcing_order(
    so_id: int,
    warehouse_id: int | None = None,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_perm("market:buy")),
):
    """Operator-side receive (orders routed to their OWN warehouse, no agent)."""
    so = _own_sourcing(db, so_id, ctx)
    if so.agent_org_id:
        raise HTTPException(400, "This order is routed via an agent — the agent receives it in the AGM")
    try:
        result = svc.receive_sourcing_order(db, so, received_by=ctx.user.id, warehouse_id=warehouse_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    data = svc.serialize_sourcing_operator(db, so, with_events=True)
    data["receive_result"] = result
    return data


def _own_sourcing(db: Session, so_id: int, ctx: AuthContext) -> m.SourcingOrder:
    so = db.get(m.SourcingOrder, so_id)
    if so is None or so.org_id != ctx.user.org_id:
        raise HTTPException(404, "Sourcing order not found")
    return so


# ---------------------------------------------------------------------------
# SUPPLIER — portal (upload + fulfil). Role-gated, org-scoped (§9).
# ---------------------------------------------------------------------------

portal = APIRouter(prefix="/market/portal", tags=["market-supplier"])


def _supplier_context(db: Session, ctx: AuthContext) -> sm.Supplier:
    """Resolve the Supplier row this portal user represents (org <-> supplier)."""
    supplier = db.query(sm.Supplier).filter(sm.Supplier.org_id == ctx.user.org_id).first()
    if supplier is None:
        raise HTTPException(403, "No supplier profile is linked to your organization")
    return supplier


@portal.get("/products")
def portal_products(db: Session = Depends(get_db), ctx: AuthContext = Depends(require_role("supplier"))):
    supplier = _supplier_context(db, ctx)
    rows = (
        db.query(m.SupplierProduct)
        .filter(m.SupplierProduct.supplier_id == supplier.id)
        .order_by(m.SupplierProduct.id.desc())
        .all()
    )
    return [svc.serialize_supplier_product(sp, supplier_view=True) for sp in rows]


@portal.post("/products", status_code=201)
def portal_upload(
    payload: SupplierProductIn,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_role("supplier")),
):
    supplier = _supplier_context(db, ctx)
    try:
        sp = svc.create_supplier_product(
            db, supplier_id=supplier.id, org_id=ctx.user.org_id,
            **payload.model_dump(),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return svc.serialize_supplier_product(sp, supplier_view=True)


@portal.patch("/products/{sp_id}")
def portal_patch_product(
    sp_id: int, payload: SupplierProductPatch,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_role("supplier")),
):
    supplier = _supplier_context(db, ctx)
    sp = _own_supplier_product(db, sp_id, supplier)
    if sp.status not in ("draft", "rejected"):
        raise HTTPException(400, "Only draft or rejected listings can be edited")
    changes = payload.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(sp, k, v)
    db.commit()
    return svc.serialize_supplier_product(sp, supplier_view=True)


@portal.post("/products/{sp_id}/submit")
def portal_submit(sp_id: int, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_role("supplier"))):
    supplier = _supplier_context(db, ctx)
    sp = _own_supplier_product(db, sp_id, supplier)
    try:
        svc.submit_for_review(db, sp)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return svc.serialize_supplier_product(sp, supplier_view=True)


@portal.get("/orders")
def portal_orders(
    status: str | None = None,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_role("supplier")),
):
    supplier = _supplier_context(db, ctx)
    q = db.query(m.SourcingOrder).filter(m.SourcingOrder.supplier_id == supplier.id)
    if status:
        q = q.filter(m.SourcingOrder.status == status)
    rows = q.order_by(m.SourcingOrder.id.desc()).limit(200).all()
    return [svc.serialize_sourcing_supplier(db, so, with_events=True) for so in rows]


@portal.post("/orders/{so_id}/accept")
def portal_accept_order(so_id: int, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_role("supplier"))):
    supplier = _supplier_context(db, ctx)
    so = _supplier_sourcing(db, so_id, supplier)
    try:
        svc.add_sourcing_event(
            db, so, code="supplier_processing",
            description="Supplier accepted the order and started processing.",
            location=f"{supplier.city or 'Origin'}, {supplier.country}",
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return svc.serialize_sourcing_supplier(db, so, with_events=True)


@portal.post("/orders/{so_id}/tracking")
def portal_tracking(
    so_id: int, payload: TrackingIn,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_role("supplier")),
):
    supplier = _supplier_context(db, ctx)
    so = _supplier_sourcing(db, so_id, supplier)
    try:
        svc.add_sourcing_event(
            db, so, code=payload.code, location=payload.location,
            description=payload.description,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return svc.serialize_sourcing_supplier(db, so, with_events=True)


def _own_supplier_product(db: Session, sp_id: int, supplier: sm.Supplier) -> m.SupplierProduct:
    sp = db.get(m.SupplierProduct, sp_id)
    if sp is None or sp.supplier_id != supplier.id:
        raise HTTPException(404, "Listing not found")
    return sp


def _supplier_sourcing(db: Session, so_id: int, supplier: sm.Supplier) -> m.SourcingOrder:
    so = db.get(m.SourcingOrder, so_id)
    if so is None or so.supplier_id != supplier.id:
        raise HTTPException(404, "Sourcing order not found")
    return so


# ---------------------------------------------------------------------------
# LUXEEN — review gate + supplier provisioning (platform staff only, §8)
# ---------------------------------------------------------------------------

admin = APIRouter(prefix="/market/admin", tags=["market-admin"])


def require_platform(ctx: AuthContext = Depends(require_auth)) -> AuthContext:
    if not ctx.is_platform:
        raise HTTPException(403, "Platform staff only")
    return ctx


@admin.get("/products")
def admin_products(
    status: str | None = None,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_platform),
):
    q = db.query(m.SupplierProduct)
    if status:
        q = q.filter(m.SupplierProduct.status == status)
    rows = q.order_by(m.SupplierProduct.id.desc()).limit(300).all()
    return [svc.serialize_supplier_product(sp, supplier_view=True) for sp in rows]


@admin.post("/products/{sp_id}/review")
def admin_review(
    sp_id: int, payload: ReviewIn,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_platform),
):
    sp = db.get(m.SupplierProduct, sp_id)
    if sp is None:
        raise HTTPException(404, "Listing not found")
    try:
        svc.review_product(db, sp, decision=payload.decision, notes=payload.notes, reviewed_by=ctx.user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return svc.serialize_supplier_product(sp, supplier_view=True)


@admin.post("/products/{sp_id}/publish")
def admin_publish(sp_id: int, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_platform)):
    sp = db.get(m.SupplierProduct, sp_id)
    if sp is None:
        raise HTTPException(404, "Listing not found")
    try:
        svc.publish_product(db, sp, published_by=ctx.user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return svc.serialize_supplier_product(sp, supplier_view=True)


@admin.post("/supplier-orgs", status_code=201)
def admin_create_supplier_org(
    payload: SupplierOrgIn,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_platform),
):
    """Recruit a supplier: org (type=supplier) + portal user + Supplier row."""
    email = payload.email.strip().lower()
    if db.query(im.User).filter(im.User.email == email).first():
        raise HTTPException(400, "Email already registered")
    org = im.Organization(
        name=payload.company.strip()[:255], type="supplier",
        country=payload.country[:2], currency="CNY",
    )
    db.add(org)
    db.flush()
    user = im.User(
        org_id=org.id, name=payload.contact_name.strip()[:255], email=email,
        role="supplier", password_hash=hash_password(payload.password),
    )
    db.add(user)
    supplier = sm.Supplier(
        name=payload.company.strip()[:255], country=payload.country[:2],
        city=payload.city, status="verified", org_id=org.id,
    )
    db.add(supplier)
    db.flush()
    publish(db, "supplier.created", {"supplier_id": supplier.id, "name": supplier.name, "org_id": org.id})
    publish(db, "user.created", {"user_id": user.id, "org_id": org.id, "role": "supplier"})
    db.commit()
    return {
        "org": {"id": org.id, "name": org.name, "type": org.type},
        "user": {"id": user.id, "email": user.email, "role": user.role},
        "supplier_id": supplier.id,
    }
