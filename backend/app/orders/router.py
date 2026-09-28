from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_perm
from app.core.events import publish
from app.crm import models as crm_m
from app.orders import models as m
from app.orders import service
from app.storefront import models as stm

router = APIRouter(
    prefix="/orders", tags=["orders"],
    dependencies=[Depends(require_perm("orders:read"))],
)


class OrderIn(BaseModel):
    store_id: int
    customer_id: int
    product_id: int
    qty: int = 1
    payment_method: str = "cod"
    delivery_fee: float = 0.0


class TransitionIn(BaseModel):
    status: str
    actor: str = "operator"


def serialize(db: Session, o: m.Order) -> dict:
    customer = db.get(crm_m.Customer, o.customer_id)
    store = db.get(stm.Store, o.store_id)
    return {
        "id": o.id, "store_id": o.store_id, "store_name": store.name if store else None,
        "customer_id": o.customer_id,
        "customer_name": customer.full_name if customer else None,
        "customer_phone": customer.phone if customer else None,
        "lead_id": o.lead_id, "status": o.status,
        "payment_method": o.payment_method, "payment_status": o.payment_status,
        "currency": o.currency, "items_total": o.items_total,
        "delivery_fee": o.delivery_fee, "total": o.total,
        "created_at": o.created_at.isoformat(),
    }


def serialize_detail(db: Session, o: m.Order) -> dict:
    data = serialize(db, o)
    customer = db.get(crm_m.Customer, o.customer_id)
    data["customer"] = {
        "id": customer.id, "full_name": customer.full_name, "phone": customer.phone,
        "address": customer.address, "city": customer.city, "state": customer.state,
        "country": customer.country,
    } if customer else None
    data["items"] = [
        {
            "id": i.id, "product_id": i.product_id, "title": i.title, "qty": i.qty,
            "unit_price": i.unit_price, "supplier_cost_cny": i.supplier_cost_cny,
        }
        for i in db.query(m.OrderItem).filter(m.OrderItem.order_id == o.id).all()
    ]
    data["allowed_transitions"] = m.ORDER_TRANSITIONS.get(o.status, [])
    return data


@router.get("")
def list_orders(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(m.Order).order_by(m.Order.id.desc())
    if status:
        q = q.filter(m.Order.status == status)
    return [serialize(db, o) for o in q.all()]


@router.post("", status_code=201, dependencies=[Depends(require_perm("orders:write"))])
def create_order(payload: OrderIn, db: Session = Depends(get_db)):
    try:
        result = service.create_order(
            db, store_id=payload.store_id, customer_id=payload.customer_id,
            product_id=payload.product_id, qty=payload.qty,
            payment_method=payload.payment_method, delivery_fee=payload.delivery_fee,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return result


@router.get("/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db)):
    o = db.get(m.Order, order_id)
    if not o:
        raise HTTPException(404, "Order not found")
    return serialize_detail(db, o)


@router.post("/{order_id}/transition", dependencies=[Depends(require_perm("orders:write"))])
def transition(order_id: int, payload: TransitionIn, db: Session = Depends(get_db)):
    o = db.get(m.Order, order_id)
    if not o:
        raise HTTPException(404, "Order not found")
    try:
        service.transition_order(db, o, payload.status, actor=payload.actor)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return serialize_detail(db, o)
