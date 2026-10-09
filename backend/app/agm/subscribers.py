"""AGM event subscribers — the alert pipeline + COD custody integrity.

agm.order_marked      -> the alert goes STRAIGHT to the agent's console and
                         notifications (the vendor 'marks it so the agent
                         can receive and alert')
agm.order_status_changed -> the vendor watches their order's local journey
agm.remittance_reconciled -> variance true-up in the ledger (§24) + vendor notice
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core import events
from app.finance import models as fm
from app.notifications import service as notif_service


def _on_order_marked(db: Session, payload: dict) -> None:
    cod = payload.get("cod_expected") or 0
    notif_service.notify(
        db, org_id=payload.get("agent_org_id"), category="agm", level="warning",
        title=f"Fulfillment alert {payload.get('code')} — call {payload.get('customer_name', 'customer')}",
        body=(
            f"{payload.get('qty')} × {payload.get('title')} for {payload.get('customer_city', '')}. "
            + (f"COD ₦{cod:,.0f} — call to confirm, then ship out." if cod else "Prepaid — call to confirm, then ship out.")
        ),
        entity_type="agent_order", entity_id=payload.get("agent_order_id"),
    )


def _on_order_status_changed(db: Session, payload: dict) -> None:
    to = payload.get("to", "")
    level = "success" if to == "delivered" else ("critical" if to == "failed" else "info")
    notif_service.notify(
        db, org_id=payload.get("vendor_org_id"), category="agm", level=level,
        title=f"Agent order {payload.get('code')}: {to.replace('_', ' ')}",
        body="Your agent updated the local delivery status."
        + (f" COD collected ₦{payload.get('cod_collected', 0):,.0f}." if to == "delivered" else ""),
        entity_type="agent_order", entity_id=payload.get("agent_order_id"),
    )


def _on_remittance_reconciled(db: Session, payload: dict) -> None:
    """Counted vs expected: a variance is a ledger true-up (§24 → §26)."""
    variance = float(payload.get("variance_amount") or 0.0)
    if abs(variance) > 0.009:
        db.add(fm.LedgerEntry(
            entry_type="cod_variance", party="agent",
            amount=round(variance, 2), currency="NGN",
            memo=f"{payload.get('register_code')} agent remittance variance (§24 true-up)",
        ))
    for vendor_org_id in payload.get("vendor_org_ids") or []:
        notif_service.notify(
            db, org_id=vendor_org_id, category="payments",
            level="info" if abs(variance) <= 0.009 else "warning",
            title=f"Agent remittance {payload.get('register_code')} reconciled",
            body=(
                f"Counted ₦{payload.get('counted_amount', 0):,.2f} vs expected "
                f"₦{payload.get('expected_amount', 0):,.2f}"
                + (f" — variance ₦{variance:,.2f}." if abs(variance) > 0.009 else ".")
            ),
            entity_type="agent_remittance", entity_id=payload.get("remittance_id"),
        )


def register() -> None:
    events.subscribe("agm.order_marked", _on_order_marked)
    events.subscribe("agm.order_status_changed", _on_order_status_changed)
    events.subscribe("agm.remittance_reconciled", _on_remittance_reconciled)
