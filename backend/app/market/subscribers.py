"""Market event subscribers — notifications + the sourcing money waterfall.

sourcing.paid (§26 waterfall, prepaid stock):
    customer→operator payment  +local_total
    supplier payable           -supplier NGN-equivalent (CNY amount in memo)
    logistics cost             -freight share
    payment cost               -processing share
    luxeen economics           -network share (the remainder)

The supplier payable lands in the same ledger the §27 settlement engine
reads — supplier settlements therefore include corridor sourcing, with the
CNY denomination carried in the memo (§46).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core import events
from app.finance import models as fm
from app.finance.economics import compute_waterfall, resolve_profile
from app.notifications import service as notif_service
from app.supply import models as sm


def _on_sourcing_paid(db: Session, payload: dict) -> None:
    amount = float(payload.get("amount_ngn") or 0.0)
    cny_total = float(payload.get("cny_total") or 0.0)
    fx = float(payload.get("fx_rate") or 0.0)
    qty = int(payload.get("qty") or 1)
    weight = float(payload.get("weight_kg") or 0.5)
    order_number = payload.get("order_number", "")
    org_id = payload.get("org_id")
    category = payload.get("category") or None
    rate_card = payload.get("rate_card") or None  # §21 snapshot from the quote

    profile = resolve_profile(
        db, org_id=org_id, origin="CN", dest="NG", category=category,
    )
    wf = compute_waterfall(
        supplier_ngn=cny_total * fx, weight_kg=weight, qty=qty,
        profile=profile, rate_card=rate_card,
    )
    supplier_ngn = wf["supplier_ngn"]
    logistics_ngn = wf["logistics_ngn"]
    payment_ngn = wf["payment_ngn"]
    luxeen_ngn = round(amount - supplier_ngn - logistics_ngn - payment_ngn, 2)

    def _add(entry_type: str, party: str, amt: float, memo: str) -> None:
        db.add(fm.LedgerEntry(
            entry_type=entry_type, party=party, amount=round(amt, 2),
            currency="NGN", memo=memo[:1024],
        ))

    basis = wf["economics_basis"]
    _add("sourcing_payment", "operator", amount, f"{order_number} marketstore sourcing payment")
    _add("supplier_payable", "supplier", -supplier_ngn,
         f"{order_number} supplier amount ¥{cny_total:,.2f} @ {fx:g} CNY→NGN (§46 snapshot)")
    _add("logistics_cost", "logistics", -logistics_ngn,
         f"{order_number} corridor logistics (freight {wf['freight_ngn']:,.0f}"
         f" + customs {wf['customs_ngn']:,.0f}) · economics: {basis['profile_name']}"
         f" / {basis.get('rate_card', 'profile per-kg')}")
    _add("payment_cost", "payment_processor", -payment_ngn, f"{order_number} payment fees")
    _add("luxeen_economics", "luxeen", luxeen_ngn, f"{order_number} network economics")
    events.publish(db, "finance.sourcing_settlement_ready", {
        "order_number": order_number, "gross_ngn": amount,
        "supplier_ngn": round(supplier_ngn, 2), "logistics_ngn": round(logistics_ngn, 2),
        "payment_ngn": round(payment_ngn, 2), "luxeen_ngn": luxeen_ngn,
    })


def _on_sourcing_submitted(db: Session, payload: dict) -> None:
    """Straight to the supplier: a new paid sourcing order to prepare."""
    supplier_id = payload.get("supplier_id")
    supplier = db.get(sm.Supplier, supplier_id) if supplier_id else None
    if supplier is None or not supplier.org_id:
        return
    notif_service.notify(
        db, org_id=supplier.org_id, category="market", level="warning",
        title=f"New sourcing order {payload.get('order_number')} — ¥{payload.get('cny_total', 0):,.2f}",
        body=(
            f"{payload.get('qty')} × {payload.get('title')} paid on Ecos. "
            f"Ship to {payload.get('dest_city')}, {payload.get('dest_country')}. "
            "Accept it in the supplier portal to start processing."
        ),
        entity_type="sourcing_order", entity_id=payload.get("sourcing_order_id"),
    )


def _on_sourcing_status_changed(db: Session, payload: dict) -> None:
    order_number = payload.get("order_number", "")
    code = payload.get("code", "")
    location = payload.get("location", "")
    notif_service.notify(
        db, org_id=payload.get("org_id"), category="market",
        level="info" if code != "delivered" else "success",
        title=f"Sourcing {order_number}: {code.replace('_', ' ')}",
        body=(location or "Checkpoint update") + " — tracked on your Sourcing page.",
        entity_type="sourcing_order", entity_id=payload.get("sourcing_order_id"),
    )


def _on_sourcing_received(db: Session, payload: dict) -> None:
    order_number = payload.get("order_number", "")
    qty = payload.get("qty")
    mode = payload.get("mode", "operator_warehouse")
    notif_service.notify(
        db, org_id=payload.get("org_id"), category="market", level="success",
        title=f"Sourcing {order_number} received — {qty} units putaway",
        body=(
            "Units landed at your agent's warehouse and are now sellable."
            if mode == "agent_putaway"
            else "Units landed in your default warehouse and are now sellable."
        ),
        entity_type="sourcing_order", entity_id=payload.get("sourcing_order_id"),
    )
    if payload.get("agent_org_id"):
        notif_service.notify(
            db, org_id=payload.get("agent_org_id"), category="agm", level="info",
            title=f"Inbound received at your warehouse — {qty} units",
            body=f"Sourcing {order_number} was checked in for your vendor's stock.",
            entity_type="sourcing_order", entity_id=payload.get("sourcing_order_id"),
        )


def _on_sourcing_delivered(db: Session, payload: dict) -> None:
    """DROPSHIP end of the corridor: the supplier's parcel reached the
    recipient's door. Tell the operator, and when this sourcing order was
    relaying a storefront customer order, walk that order down its §19
    machine to `delivered` (mirrors the AGM hand-off, minus the agent).

    §9 money rule: the supplier's leg is prepaid corridor freight — retail
    COD never touches the supplier. A COD storefront order stays
    payment_status=pending for the operator to collect through their own
    channel (the payments desk captures it when the cash lands).
    """
    order_number = payload.get("order_number", "")
    org_id = payload.get("org_id")
    title = payload.get("title", "")
    qty = payload.get("qty", 1)
    notif_service.notify(
        db, org_id=org_id, category="market", level="success",
        title=f"Dropship {order_number} delivered to the recipient",
        body=(
            f"{qty} × {title} was handed over at the recipient's door — "
            "no stock landed; the corridor leg is complete."
        ),
        entity_type="sourcing_order", entity_id=payload.get("sourcing_order_id"),
    )

    order_id = payload.get("customer_order_id")
    if not order_id:
        return
    from app.orders import models as om
    from app.orders import service as order_service

    order = db.get(om.Order, int(order_id))
    if order is None or order.status == "delivered":
        return
    chain = ["processing", "fulfilled", "in_transit", "out_for_delivery", "delivered"]
    if order.status == "confirmed":
        steps = chain
    elif order.status in chain:
        steps = chain[chain.index(order.status) + 1:]
    else:
        return  # unexpected state — never force a machine backwards
    for step in steps:
        try:
            order_service.transition_order(db, order, step, actor="supplier_dropship")
        except ValueError:
            break
        if order.status == "delivered":
            break
    notif_service.notify(
        db, org_id=org_id, category="orders", level="success",
        title=f"Order #{order.id} fulfilled by supplier dropship",
        body=(
            f"The supplier delivered {qty} × {title} directly to "
            f"{payload.get('recipient', 'the customer')}. "
            + (
                "COD is still pending — collect through your own channel and capture it in Payments."
                if order.payment_method == "cod"
                else "Payment was already captured."
            )
        ),
        entity_type="order", entity_id=order.id,
    )


def register() -> None:
    events.subscribe("sourcing.paid", _on_sourcing_paid)
    events.subscribe("sourcing.submitted", _on_sourcing_submitted)
    events.subscribe("sourcing.status_changed", _on_sourcing_status_changed)
    events.subscribe("sourcing.received", _on_sourcing_received)
    events.subscribe("sourcing.delivered", _on_sourcing_delivered)
