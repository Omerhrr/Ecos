"""Warehouse / fulfillment API (plan §22 deep-dive).

Read paths need `warehouse:read`; anything that moves or corrects stock
(create/adjust/transfer, wave lifecycle) needs `warehouse:write`.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import AuthContext, require_auth, require_perm
from app.warehouse import models as m
from app.warehouse import service as svc

router = APIRouter(
    prefix="/warehouse", tags=["warehouse"],
    dependencies=[Depends(require_perm("warehouse:read"))],
)


# ------------------------------------------------------------------ warehouses

@router.get("")
def list_warehouses(db: Session = Depends(get_db)):
    whs = db.query(m.Warehouse).order_by(m.Warehouse.id).all()
    return [svc.serialize_warehouse(db, wh) for wh in whs]


class WarehouseIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    city: str = ""
    country: str = "NG"
    address: str = ""
    is_default: bool = False


@router.post("", status_code=201, dependencies=[Depends(require_perm("warehouse:write"))])
def create_warehouse(payload: WarehouseIn, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_auth)):
    wh = svc.create_warehouse(
        db, name=payload.name, org_id=ctx.user.org_id, city=payload.city,
        country=payload.country, address=payload.address, is_default=payload.is_default,
    )
    db.commit()
    return svc.serialize_warehouse(db, wh)


# ------------------------------------------------------------------ stock

@router.get("/overview")
def stock_overview(
    warehouse_id: int | None = None,
    product_id: int | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(m.StockItem).order_by(m.StockItem.warehouse_id, m.StockItem.product_id)
    if warehouse_id:
        q = q.filter(m.StockItem.warehouse_id == warehouse_id)
    if product_id:
        q = q.filter(m.StockItem.product_id == product_id)
    return [svc.serialize_stock_row(db, it) for it in q.limit(500).all()]


@router.get("/movements")
def stock_movements(
    warehouse_id: int | None = None,
    product_id: int | None = None,
    movement_type: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    q = db.query(m.StockMovement).order_by(m.StockMovement.id.desc())
    if warehouse_id:
        q = q.filter(m.StockMovement.warehouse_id == warehouse_id)
    if product_id:
        q = q.filter(m.StockMovement.product_id == product_id)
    if movement_type:
        q = q.filter(m.StockMovement.movement_type == movement_type)
    return [svc.serialize_movement(db, mv) for mv in q.limit(min(limit, 500)).all()]


class AdjustIn(BaseModel):
    warehouse_id: int
    product_id: int
    delta: int
    reason: str = Field(min_length=3, max_length=1024)


@router.post("/adjust", dependencies=[Depends(require_perm("warehouse:write"))])
def adjust_stock(payload: AdjustIn, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_auth)):
    from app.catalog import models as cm

    product = db.get(cm.Product, payload.product_id)
    if product is None:
        raise HTTPException(404, "Product not found")
    wh = db.get(m.Warehouse, payload.warehouse_id)
    if wh is None:
        raise HTTPException(404, "Warehouse not found")
    try:
        svc.adjust_stock(
            db, warehouse_id=payload.warehouse_id, product=product,
            delta=payload.delta, reason=payload.reason, created_by=ctx.user.id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return {"ok": True, "product_id": product.id, "product_stock": product.stock}


class TransferIn(BaseModel):
    from_warehouse_id: int
    to_warehouse_id: int
    product_id: int
    qty: int = Field(ge=1)


@router.post("/transfer", dependencies=[Depends(require_perm("warehouse:write"))])
def transfer_stock(payload: TransferIn, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_auth)):
    from app.catalog import models as cm

    product = db.get(cm.Product, payload.product_id)
    if product is None:
        raise HTTPException(404, "Product not found")
    try:
        movements = svc.transfer_stock(
            db, from_warehouse_id=payload.from_warehouse_id,
            to_warehouse_id=payload.to_warehouse_id, product=product,
            qty=payload.qty, created_by=ctx.user.id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return {"ok": True, "movement_ids": [mv.id for mv in movements]}


# ------------------------------------------------------------------ pick waves

@router.get("/waves")
def list_waves(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(m.PickWave).order_by(m.PickWave.id.desc())
    if status:
        q = q.filter(m.PickWave.status == status)
    return [svc.serialize_wave(db, w, with_lines=True) for w in q.limit(100).all()]


class WaveIn(BaseModel):
    order_ids: list[int]
    warehouse_id: int | None = None
    note: str = ""


@router.post("/waves", status_code=201, dependencies=[Depends(require_perm("warehouse:write"))])
def create_wave(payload: WaveIn, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_auth)):
    try:
        wave = svc.create_wave(
            db, warehouse_id=payload.warehouse_id, order_ids=payload.order_ids,
            created_by=ctx.user.id, org_id=ctx.user.org_id, note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return svc.serialize_wave(db, wave, with_lines=True)


def _wave_or_404(db: Session, wave_id: int) -> m.PickWave:
    wave = db.get(m.PickWave, wave_id)
    if not wave:
        raise HTTPException(404, "Pick wave not found")
    return wave


@router.post("/waves/{wave_id}/pick", dependencies=[Depends(require_perm("warehouse:write"))])
def pick_wave(wave_id: int, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_auth)):
    wave = _wave_or_404(db, wave_id)
    try:
        svc.pick_wave(db, wave, actor=ctx.user.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return svc.serialize_wave(db, wave, with_lines=True)


@router.post("/waves/{wave_id}/pack", dependencies=[Depends(require_perm("warehouse:write"))])
def pack_wave(wave_id: int, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_auth)):
    wave = _wave_or_404(db, wave_id)
    try:
        svc.pack_wave(db, wave, actor=ctx.user.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return svc.serialize_wave(db, wave, with_lines=True)


@router.post("/waves/{wave_id}/complete", dependencies=[Depends(require_perm("warehouse:write"))])
def complete_wave(wave_id: int, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_auth)):
    wave = _wave_or_404(db, wave_id)
    try:
        svc.complete_wave(db, wave, actor=ctx.user.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return svc.serialize_wave(db, wave, with_lines=True)


@router.post("/waves/{wave_id}/cancel", dependencies=[Depends(require_perm("warehouse:write"))])
def cancel_wave(wave_id: int, db: Session = Depends(get_db), ctx: AuthContext = Depends(require_auth)):
    wave = _wave_or_404(db, wave_id)
    try:
        svc.cancel_wave(db, wave, actor=ctx.user.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return svc.serialize_wave(db, wave, with_lines=True)
