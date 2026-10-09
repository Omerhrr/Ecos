"""Deterministic event subscribers (plan §41 — automation engine, Phase 1).

Wiring:
  order.status_changed(delivered)
      -> COD payment auto-captured            (payment.received)
  payment.received
      -> ledger waterfall entries             (§26, §27)
  shipment.delivered
      -> (hook point for notifications / settlement start — Phase 2)

AI-driven interpretation (§31) plugs in here later; deterministic rules
run first, exactly as the plan prescribes.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.catalog import models as cm
from app.core import events
from app.core.pricing import FX_RATES
from app.finance import models as fm
from app.finance.economics import compute_waterfall, resolve_profile
from app.orders import models as om
from app.payments import models as pm
from app.payments import service as payment_service
from app.storefront import models as stm


def _on_order_status_changed(db: Session, payload: dict) -> None:
    if payload.get("to") != "delivered":
        return
    # DROPSHIP (§9): the supplier's courier completed the last mile, but no
    # cash moved through Ecos — the operator collects COD through their own
    # channel and captures it in Payments. Auto-capture stays honest for the
    # AGM path, where the agent physically holds the COD at the door.
    if payload.get("actor") == "supplier_dropship":
        return
    order_id = payload["order_id"]
    order = db.get(om.Order, order_id)
    if order is None:
        return
    payment = (
        db.query(pm.Payment).filter(pm.Payment.order_id == order_id).first()
    )
    if payment and payment.method == "cod" and payment.status == "pending":
        # COD: customer pays the courier at the door — collect now (§24)
        payment_service.capture_payment(db, payment, reference=f"COD-{payment.id:08d}")
        payment_service.sync_order_payment_status(db, order_id)


def _on_payment_received(db: Session, payload: dict) -> None:
    order_id = payload["order_id"]
    amount = payload["amount"]
    order = db.get(om.Order, order_id)
    if order is None:
        return
    items = db.query(om.OrderItem).filter(om.OrderItem.order_id == order_id).all()
    if not items:
        return

    # §57: the waterfall's rates are DATA — resolve the most specific
    # active profile for this operator/category instead of constants.
    store = db.get(stm.Store, order.store_id)
    first_product = db.get(cm.Product, items[0].product_id) if items else None
    profile = resolve_profile(
        db,
        org_id=store.org_id if store else None,
        origin="CN", dest="NG",
        category=first_product.category if first_product else None,
    )

    # Waterfall per unit economics captured at order time (§27)
    supplier_cny = sum(i.supplier_cost_cny * i.qty for i in items)
    fx = FX_RATES["CNY"]["NGN"]
    supplier_ngn = supplier_cny * fx
    weight_kg = sum(i.weight_kg * i.qty for i in items)
    wf = compute_waterfall(
        supplier_ngn=supplier_ngn, weight_kg=weight_kg, qty=1,
        profile=profile,
    )
    logistics_ngn = wf["logistics_ngn"]
    payment_ngn = wf["payment_ngn"]
    luxeen_ngn = wf["luxeen_ngn"]
    operator_ngn = amount - supplier_ngn - logistics_ngn - payment_ngn - luxeen_ngn

    def _add(entry_type: str, party: str, amt: float, memo: str) -> None:
        db.add(fm.LedgerEntry(
            order_id=order_id, entry_type=entry_type, party=party,
            amount=round(amt, 2), currency="NGN", memo=memo,
        ))

    basis = wf["economics_basis"]
    basis_memo = f"economics: {basis['profile_name']}" + (
        f" / {basis['rate_card']}" if basis.get("rate_card") else ""
    )
    _add("customer_payment", "customer", amount, f"Order {order_id} payment ({payload.get('method', 'cod')})")
    _add("supplier_payable", "supplier", -supplier_ngn, f"Order {order_id} supplier amount")
    _add("logistics_cost", "logistics", -logistics_ngn,
         f"Order {order_id} logistics (freight {wf['freight_ngn']:,.0f}"
         f" + customs {wf['customs_ngn']:,.0f}) · {basis_memo}")
    _add("payment_cost", "payment_processor", -payment_ngn, f"Order {order_id} payment fees")
    _add("luxeen_economics", "luxeen", -luxeen_ngn, f"Order {order_id} network economics")
    _add("operator_economics", "operator", -operator_ngn, f"Order {order_id} operator economics")

    events.publish(db, "finance.settlement_ready", {
        "order_id": order_id, "gross_ngn": amount,
        "supplier_ngn": round(supplier_ngn, 2), "logistics_ngn": round(logistics_ngn, 2),
        "payment_ngn": round(payment_ngn, 2), "luxeen_ngn": round(luxeen_ngn, 2),
        "operator_ngn": round(operator_ngn, 2),
    })


def _on_payment_refunded(db: Session, payload: dict) -> None:
    """Refund money-out entry (§26, §28). Amount arrives pre-signed (negative)."""
    order_id = payload["order_id"]
    amount = payload["amount"]
    memo = f"Order {order_id} refund"
    if payload.get("reference"):
        memo += f" ({payload['reference']})"
    db.add(fm.LedgerEntry(
        order_id=order_id, entry_type="refund", party="customer",
        amount=round(amount, 2), currency=payload.get("currency", "NGN"),
        memo=memo,
    ))


def register_all() -> None:
    events.subscribe("order.status_changed", _on_order_status_changed)
    events.subscribe("payment.received", _on_payment_received)
    events.subscribe("payment.refunded", _on_payment_refunded)

    # §39 notifications + procurement (Stock Prophet -> suggestions) wiring.
    # Imported lazily: these modules import domain models that live above core.
    from app.notifications import subscribers as notification_subscribers
    from app.procurement import subscribers as procurement_subscribers
    from app.warehouse import subscribers as warehouse_subscribers
    from app.automation import service as automation_service

    notification_subscribers.register()
    procurement_subscribers.register()
    warehouse_subscribers.register()

    # Marketstore + sourcing (§8-11, §20, §23, §26) and the AGM (§24):
    # alert pipelines, ledger waterfall for prepaid sourcing, COD custody.
    from app.market import subscribers as market_subscribers
    from app.agm import subscribers as agm_subscribers

    market_subscribers.register()
    agm_subscribers.register()

    # §41: the automation engine offers every catalog event to operator rules
    automation_service.register_dispatcher()
