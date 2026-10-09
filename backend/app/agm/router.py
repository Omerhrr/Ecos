"""AGM router — agent console + operator-facing agent management.

  /agm/register, /agm/directory        public signup + operator browsing
  /agm/links, /agm/orders/*/mark       operator side (add agent, mark order)
  /agm/overview|warehouses|stock|...   agent console (role-gated, org-scoped)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agm import models as m
from app.agm import service as svc
from app.core.database import get_db
from app.core.deps import AuthContext, require_auth, require_perm, require_role
from app.core.events import publish
from app.core.security import hash_password
from app.identity import models as im
from app.orders import models as om

router = APIRouter(prefix="/agm", tags=["agm"])


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------

class AgentRegisterIn(BaseModel):
    company: str
    contact_name: str
    email: str
    password: str = Field(min_length=6)
    phone: str = ""
    whatsapp: str = ""
    city: str = ""
    country: str = "NG"
    address: str = ""


class LinkIn(BaseModel):
    agent_org_id: int


class MarkIn(BaseModel):
    agent_org_id: int


class WarehouseIn(BaseModel):
    name: str
    city: str = ""
    country: str = "NG"
    address: str = ""
    is_default: bool = False


class ActionIn(BaseModel):
    action: str  # accept | start_call | confirm | out_for_delivery | deliver | fail | return | cancel
    cod_collected: float | None = None
    note: str = ""
    failed_reason: str = ""


class RemittanceIn(BaseModel):
    vendor_org_id: int | None = None
    agent_order_ids: list[int] = []
    reference: str = ""
    note: str = ""


class ReconcileIn(BaseModel):
    counted: dict[str, float] = {}  # line_id -> counted amount


# ---------------------------------------------------------------------------
# Public + operator side
# ---------------------------------------------------------------------------

@router.post("/register", status_code=201)
def register_agent(payload: AgentRegisterIn, db: Session = Depends(get_db)):
    """Self-service agent signup (plan: 'people can register as agent')."""
    try:
        result = svc.register_agent(
            db, company=payload.company, contact_name=payload.contact_name,
            email=payload.email, password_hash=hash_password(payload.password),
            phone=payload.phone, whatsapp=payload.whatsapp,
            city=payload.city, country=payload.country, address=payload.address,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return result


@router.get("/directory")
def agent_directory(db: Session = Depends(get_db), ctx: AuthContext = Depends(require_auth)):
    """Agents vendors can add. If the caller is an operator, their existing
    links are flagged so the UI can show 'Added'."""
    profiles = (
        db.query(m.AgentProfile)
        .filter(m.AgentProfile.status == "active")
        .order_by(m.AgentProfile.org_id)
        .all()
    )
    my_links: dict[int, str] = {}
    if ctx.org and ctx.org.type == "operator":
        for link in db.query(m.AgentLink).filter(m.AgentLink.vendor_org_id == ctx.user.org_id).all():
            my_links[link.agent_org_id] = link.status
    return [
        {**svc.serialize_agent_card(db, p), "link_status": my_links.get(p.org_id)}
        for p in profiles
    ]


@router.get("/links")
def my_links(db: Session = Depends(get_db), ctx: AuthContext = Depends(require_auth)):
    """Vendor: my agents. Agent: my vendors."""
    if ctx.org and ctx.org.type == "agent":
        rows = db.query(m.AgentLink).filter(m.AgentLink.agent_org_id == ctx.user.org_id).all()
        return [
            {
                "id": l.id, "agent_org_id": l.agent_org_id, "vendor_org_id": l.vendor_org_id,
                "vendor_name": (db.get(im.Organization, l.vendor_org_id).name if db.get(im.Organization, l.vendor_org_id) else f"Org {l.vendor_org_id}"),
                "status": l.status,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in rows
        ]
    rows = db.query(m.AgentLink).filter(m.AgentLink.vendor_org_id == ctx.user.org_id).all()
    out = []
    for l in rows:
        org = db.get(im.Organization, l.agent_org_id)
        profile = db.get(m.AgentProfile, l.agent_org_id)
        out.append({
            "id": l.id, "agent_org_id": l.agent_org_id,
            "agent_name": org.name if org else f"Agent {l.agent_org_id}",
            "city": profile.city if profile else "",
            "phone": profile.phone if profile else "",
            "warehouses": (
                db.query(m.AgentWarehouse).filter(m.AgentWarehouse.agent_org_id == l.agent_org_id).count()
                if profile else 0
            ),
            "status": l.status,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        })
    return out


@router.post("/links", status_code=201)
def add_link(payload: LinkIn, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_perm("orders:write"))):
    try:
        svc.add_link(db, agent_org_id=payload.agent_org_id, vendor_org_id=ctx.user.org_id, created_by=ctx.user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return {"ok": True, "agent_org_id": payload.agent_org_id}


@router.post("/orders/{order_id}/mark", status_code=201)
def mark_order(
    order_id: int, payload: MarkIn,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_perm("orders:write")),
):
    """Vendor confirms the customer wants to buy -> mark it so the agent
    receives the alert and can start calling (the AGM handshake)."""
    order = db.get(om.Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found")
    # vendor scope: order must belong to a store of the caller's org
    from app.storefront import models as stm

    store = db.get(stm.Store, order.store_id)
    if store is None or store.org_id != ctx.user.org_id:
        raise HTTPException(404, "Order not found")
    try:
        ao = svc.mark_order_for_agent(
            db, order=order, agent_org_id=payload.agent_org_id,
            vendor_org_id=ctx.user.org_id, created_by=ctx.user.id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return svc.serialize_agent_order(ao)


@router.get("/vendor-orders")
def vendor_orders(
    status: str | None = None,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_perm("orders:read")),
):
    q = db.query(m.AgentOrder).filter(m.AgentOrder.vendor_org_id == ctx.user.org_id)
    if status:
        q = q.filter(m.AgentOrder.status == status)
    rows = q.order_by(m.AgentOrder.id.desc()).limit(200).all()
    return [svc.serialize_agent_order(ao) for ao in rows]


# ---------------------------------------------------------------------------
# Agent console (role=agm, org-scoped)
# ---------------------------------------------------------------------------

@router.get("/overview")
def agent_overview(db: Session = Depends(get_db), ctx: AuthContext = Depends(require_role("agm"))):
    org_id = ctx.user.org_id
    queue = (
        db.query(m.AgentOrder)
        .filter(m.AgentOrder.agent_org_id == org_id)
        .order_by(m.AgentOrder.id.desc())
        .all()
    )
    by_status: dict[str, int] = {}
    for ao in queue:
        by_status[ao.status] = by_status.get(ao.status, 0) + 1
    cod_awaiting = sum(ao.cod_collected for ao in queue if ao.status == "delivered" and ao.remittance_id is None)
    vendors = db.query(m.AgentLink).filter(m.AgentLink.agent_org_id == org_id, m.AgentLink.status == "active").count()
    warehouses = db.query(m.AgentWarehouse).filter(m.AgentWarehouse.agent_org_id == org_id, m.AgentWarehouse.status == "active").count()
    stock_units = (
        db.query(m.AgentStockItem)
        .filter(m.AgentStockItem.agent_org_id == org_id)
        .all()
    )
    return {
        "company": ctx.org.name if ctx.org else f"Agent {org_id}",
        "vendors": vendors,
        "warehouses": warehouses,
        "queue": by_status,
        "pending_alerts": by_status.get("notified", 0),
        "cod_awaiting_remit": round(cod_awaiting, 2),
        "units_held": sum(i.on_hand for i in stock_units),
    }


@router.get("/warehouses")
def agent_warehouses(db: Session = Depends(get_db), ctx: AuthContext = Depends(require_role("agm"))):
    rows = (
        db.query(m.AgentWarehouse)
        .filter(m.AgentWarehouse.agent_org_id == ctx.user.org_id)
        .order_by(m.AgentWarehouse.id)
        .all()
    )
    return [
        {
            "id": w.id, "code": w.code, "name": w.name, "city": w.city,
            "country": w.country, "address": w.address, "is_default": bool(w.is_default),
            "status": w.status,
        }
        for w in rows
    ]


@router.post("/warehouses", status_code=201)
def agent_create_warehouse(payload: WarehouseIn, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_role("agm"))):
    wh = svc.create_warehouse(
        db, agent_org_id=ctx.user.org_id, name=payload.name, city=payload.city,
        country=payload.country, address=payload.address, is_default=payload.is_default,
    )
    db.commit()
    return {"id": wh.id, "code": wh.code, "name": wh.name}


@router.get("/stock")
def agent_stock(
    warehouse_id: int | None = None,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_role("agm")),
):
    return svc.agent_stock(db, agent_org_id=ctx.user.org_id, warehouse_id=warehouse_id)


@router.post("/receive-sourcing/{so_id}")
def agent_receive_sourcing(
    so_id: int,
    warehouse_id: int | None = None,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_role("agm")),
):
    """Sourcing goods arrived at the agent's dock: check them in as PER-VENDOR
    stock (§20 x §22). Only the agent the order is routed to can receive."""
    from app.market import models as market_m
    from app.market import service as market_service

    so = db.get(market_m.SourcingOrder, so_id)
    if so is None or so.agent_org_id != ctx.user.org_id:
        raise HTTPException(404, "Sourcing order not found for this agent")
    try:
        result = market_service.receive_sourcing_order(
            db, so, received_by=ctx.user.id, warehouse_id=warehouse_id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return {
        "ok": True, "mode": result.get("mode"),
        "warehouse": result.get("agent_warehouse"),
        "qty": so.qty, "status": so.status,
    }


@router.get("/orders")
def agent_queue(
    status: str | None = None,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_role("agm")),
):
    q = db.query(m.AgentOrder).filter(m.AgentOrder.agent_org_id == ctx.user.org_id)
    if status:
        q = q.filter(m.AgentOrder.status == status)
    rows = q.order_by(m.AgentOrder.id.desc()).limit(200).all()
    return [svc.serialize_agent_order(ao) for ao in rows]


@router.post("/orders/{ao_id}/action")
def agent_order_action(
    ao_id: int, payload: ActionIn,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_role("agm")),
):
    ao = db.get(m.AgentOrder, ao_id)
    if ao is None or ao.agent_org_id != ctx.user.org_id:
        raise HTTPException(404, "Alert not found")
    try:
        svc.agent_order_action(
            db, ao, payload.action, actor=ctx.user.id,
            cod_collected=payload.cod_collected, note=payload.note,
            failed_reason=payload.failed_reason,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return svc.serialize_agent_order(ao)


@router.get("/remittances")
def agent_remittances(db: Session = Depends(get_db), ctx: AuthContext = Depends(require_role("agm"))):
    rows = (
        db.query(m.AgentRemittance)
        .filter(m.AgentRemittance.agent_org_id == ctx.user.org_id)
        .order_by(m.AgentRemittance.id.desc())
        .limit(100)
        .all()
    )
    return [svc.serialize_remittance(db, r, with_lines=True) for r in rows]


@router.post("/remittances", status_code=201)
def agent_create_remittance(payload: RemittanceIn, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_role("agm"))):
    try:
        reg = svc.create_remittance(
            db, agent_org_id=ctx.user.org_id, vendor_org_id=payload.vendor_org_id,
            agent_order_ids=payload.agent_order_ids or None,
            reference=payload.reference, note=payload.note,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return svc.serialize_remittance(db, reg, with_lines=True)


@router.post("/remittances/{reg_id}/remit")
def agent_remit(reg_id: int, body: dict | None = None, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_role("agm"))):
    reg = db.get(m.AgentRemittance, reg_id)
    if reg is None or reg.agent_org_id != ctx.user.org_id:
        raise HTTPException(404, "Register not found")
    try:
        svc.remit(db, reg, reference=(body or {}).get("reference", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return svc.serialize_remittance(db, reg, with_lines=True)


@router.post("/remittances/{reg_id}/reconcile")
def agent_reconcile(reg_id: int, payload: ReconcileIn, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_role("agm"))):
    reg = db.get(m.AgentRemittance, reg_id)
    if reg is None or reg.agent_org_id != ctx.user.org_id:
        raise HTTPException(404, "Register not found")
    counted = {int(k): float(v) for k, v in (payload.counted or {}).items()}
    try:
        svc.reconcile(db, reg, counted)
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    return svc.serialize_remittance(db, reg, with_lines=True)


@router.patch("/profile")
def agent_patch_profile(body: dict, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_role("agm"))):
    profile = db.get(m.AgentProfile, ctx.user.org_id)
    if profile is None:
        raise HTTPException(404, "Profile not found")
    for k in ("contact_name", "phone", "whatsapp", "city", "address", "capacity_note"):
        if k in body and body[k] is not None:
            setattr(profile, k, str(body[k])[:1024])
    db.commit()
    return {"ok": True}
