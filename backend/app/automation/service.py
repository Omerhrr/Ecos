"""Automation Engine service (plan §41).

The engine sits on the domain event bus (§40). Every published event is
offered to every enabled rule watching that event type:

    WHEN  event_type matches
    AND   every condition holds (dot-path lookup into the payload)
    THEN  each action executes deterministically, inside the same
          transaction as the triggering operation

Every evaluation writes an `automation_runs` audit row — matched or not —
so "what happened and why" is always answerable (§44). Each rule's action
block runs inside a SAVEPOINT: a broken rule rolls back to the event state
and logs `failed` without harming the triggering operation.

Actions available:
    notify                  in-app notification ({{path}} template interpolation)
    escalate                critical-level notification for the ops floor
    flag_product            surface a product for review (catalog watchers)
    create_settlement_draft open a §27 draft run from unsettled payables
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.automation import models as m

# --------------------------------------------------------------------------
# Event catalog — what rules can watch (kept in step with the publishers)
# --------------------------------------------------------------------------

EVENT_CATALOG: list[dict[str, str]] = [
    {"name": "order.created", "label": "Order created", "sample": '{"order_id": 12, "total_ngn": 42000, "payment_method": "cod"}'},
    {"name": "order.status_changed", "label": "Order status changed", "sample": '{"order_id": 12, "from": "in_transit", "to": "delivered"}'},
    {"name": "shipment.created", "label": "Shipment created", "sample": '{"shipment_id": 5, "order_id": 12, "tracking_code": "ECOS-NG-..."}'},
    {"name": "shipment.updated", "label": "Shipment checkpoint added", "sample": '{"shipment_id": 5, "order_id": 12, "code": "customs", "status": "in_transit"}'},
    {"name": "shipment.delivered", "label": "Shipment delivered", "sample": '{"shipment_id": 5, "order_id": 12}'},
    {"name": "payment.received", "label": "Payment captured", "sample": '{"order_id": 12, "amount": 42000, "method": "cod"}'},
    {"name": "payment.refunded", "label": "Payment refunded", "sample": '{"order_id": 12, "amount": -42000}'},
    {"name": "return.requested", "label": "RMA requested", "sample": '{"rma_id": 3, "rma_number": "RMA-00003", "order_id": 12, "reason": "defective"}'},
    {"name": "return.status_changed", "label": "RMA status changed", "sample": '{"rma_id": 3, "from": "requested", "to": "approved"}'},
    {"name": "warehouse.return_restocked", "label": "Return restocked to shelf", "sample": '{"rma_id": 3, "warehouse_code": "WH-001", "units": 2}'},
    {"name": "warehouse.stock_adjusted", "label": "Stock adjusted", "sample": '{"warehouse_id": 1, "product_id": 4, "delta": -2, "on_hand": 88}'},
    {"name": "warehouse.stock_transferred", "label": "Stock transferred", "sample": '{"product_id": 4, "qty": 5}'},
    {"name": "warehouse.wave_completed", "label": "Pick wave completed", "sample": '{"wave_id": 7, "shipment_ids": [9]}'},
    {"name": "reorder.suggested", "label": "Stock Prophet reorder suggestions", "sample": '{"run_id": 2, "fresh_count": 2}'},
    {"name": "procurement.po_received", "label": "PO goods received", "sample": '{"po_id": 1, "po_number": "PO-00001"}'},
    {"name": "procurement.po_status_changed", "label": "PO status changed", "sample": '{"po_id": 1, "from": "submitted", "to": "confirmed"}'},
    {"name": "settlement.created", "label": "Settlement run drafted", "sample": '{"run_id": 3, "total_amount": 91000}'},
    {"name": "settlement.completed", "label": "Settlement executed", "sample": '{"run_id": 3, "total_amount": 91000}'},
    {"name": "finance.settlement_ready", "label": "Payment waterfall ready to settle", "sample": '{"order_id": 12, "gross_ngn": 42000}'},
    {"name": "lead.created", "label": "Lead created", "sample": '{"lead_id": 8, "source": "storefront", "campaign": "q3-lagos-electronics"}'},
    {"name": "lead.updated", "label": "Lead updated", "sample": '{"lead_id": 8, "changes": ["status"]}'},
    {"name": "storefront.checkout_completed", "label": "Storefront checkout completed", "sample": '{"order_id": 12, "total_ngn": 42000, "utm": {}}'},
    {"name": "ai.run.completed", "label": "AI operator run completed", "sample": '{"operator": "Stock Prophet", "provider": "deepseek"}'},
    {"name": "ai.run.failed", "label": "AI operator run failed", "sample": '{"operator": "Stock Prophet", "error": "timeout"}'},
    {"name": "ai.proposal.approved", "label": "AI proposal approved", "sample": '{"operator": "Launch Scribe", "run_id": 9}'},
]

EVENT_LABELS: dict[str, str] = {e["name"]: e["label"] for e in EVENT_CATALOG}


# --------------------------------------------------------------------------
# Condition evaluation
# --------------------------------------------------------------------------

def _dig(payload: dict, path: str) -> tuple[bool, Any]:
    """Dot-path lookup: "order.id" -> payload["order"]["id"]. Missing -> (False, None)."""
    cur: Any = payload
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return False, None
    return True, cur


def _to_num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def eval_condition(payload: dict, cond: dict) -> dict:
    """Evaluate one condition against the payload. Never raises."""
    path = str(cond.get("path") or "")
    op = str(cond.get("op") or "eq")
    want = cond.get("value")
    found, actual = _dig(payload, path)

    if op == "exists":
        ok = found
    elif not found:
        ok = False
    elif op == "truthy":
        ok = bool(actual)
    elif op == "eq":
        ok = actual == want or str(actual) == str(want)
    elif op == "ne":
        ok = not (actual == want or str(actual) == str(want))
    elif op in ("gt", "gte", "lt", "lte"):
        a, w = _to_num(actual), _to_num(want)
        ok = a is not None and w is not None and (
            a > w if op == "gt" else a >= w if op == "gte" else a < w if op == "lt" else a <= w
        )
    elif op == "contains":
        ok = str(want).lower() in str(actual).lower()
    elif op == "in":
        ok = isinstance(want, list) and str(actual) in [str(x) for x in want]
    elif op == "not_in":
        ok = not (isinstance(want, list) and str(actual) in [str(x) for x in want])
    else:
        ok = False

    return {"path": path, "op": op, "value": want, "actual": actual if found else None, "ok": bool(ok)}


def eval_conditions(payload: dict, conditions: list[dict]) -> list[dict]:
    return [eval_condition(payload, c) for c in conditions or []]


# --------------------------------------------------------------------------
# Action execution
# --------------------------------------------------------------------------

_TMPL = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


def _render(template: str, payload: dict) -> str:
    """Replace {{order_id}} / {{rma.rma_number}}-style tokens from the payload."""
    def sub(match: re.Match) -> str:
        found, value = _dig(payload, match.group(1))
        return str(value) if found and value is not None else ""
    return _TMPL.sub(sub, str(template))


def _execute_action(db: Session, rule: m.AutomationRule, action: dict, payload: dict) -> dict:
    from app.notifications import service as notif_service  # lazy: avoid import cycle

    kind = action.get("type")
    if kind in ("notify", "escalate"):
        title = _render(action.get("title") or f"Automation: {rule.name}", payload)
        body = _render(action.get("body") or "", payload)
        rows = notif_service.notify(
            db,
            org_id=rule.org_id,
            category=action.get("category") or "automation",
            level="critical" if kind == "escalate" else action.get("level") or "info",
            title=title[:255],
            body=body[:1024],
            entity_type="automation_rule", entity_id=rule.id,
            meta={"rule_id": rule.id},
        )
        return {"type": kind, "notifications": len(rows), "title": title}

    if kind == "flag_product":
        product_id = action.get("product_id")
        if not product_id:
            product_id = _dig(payload, action.get("product_path") or "product_id")[1]
        reason = _render(action.get("reason") or f"Flagged by rule {rule.name}", payload)
        rows = notif_service.notify(
            db,
            org_id=rule.org_id, category="catalog", level="warning",
            title=f"Product {product_id} flagged for review",
            body=reason[:1024],
            entity_type="product", entity_id=int(product_id) if product_id else None,
            meta={"rule_id": rule.id},
        )
        return {"type": kind, "product_id": product_id, "notifications": len(rows), "reason": reason}

    if kind == "create_settlement_draft":
        from app.settlements import service as settlement_service  # lazy

        try:
            run = settlement_service.build_run(
                db,
                note=f"Automation rule '{rule.name}' opened this draft",
                org_id=rule.org_id,
            )
        except ValueError as exc:
            return {"type": kind, "skipped": True, "reason": str(exc)}
        return {"type": kind, "run_id": run.id, "run_number": run.run_number,
                "total_amount": run.total_amount, "currency": run.currency}

    raise ValueError(f"Unknown action type: {kind}")


# --------------------------------------------------------------------------
# The engine
# --------------------------------------------------------------------------

def _as_aware(dt: datetime) -> datetime:
    """SQLite returns naive datetimes — treat stored values as UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _in_cooldown(rule: m.AutomationRule, now: datetime) -> bool:
    if not rule.cooldown_seconds or not rule.last_matched_at:
        return False
    return now < _as_aware(rule.last_matched_at) + timedelta(seconds=rule.cooldown_seconds)


def handle_event(db: Session, event_type: str, payload: dict, *,
                 event_row_id: int | None = None, dry_run: bool = False) -> list[dict]:
    """Offer an event to every enabled rule watching it. Returns audit summaries."""
    from app.core import events as bus  # lazy

    rules = (
        db.query(m.AutomationRule)
        .filter(m.AutomationRule.event_type == event_type, m.AutomationRule.enabled == 1)
        .order_by(m.AutomationRule.id.asc())
        .all()
    )
    now = datetime.now(timezone.utc)
    results: list[dict] = []
    for rule in rules:
        conditions_result = eval_conditions(payload, rule.conditions)
        failed = [c for c in conditions_result if not c["ok"]]
        executed: list[dict] = []
        error = ""

        if failed:
            status = "condition_not_met"
        elif not dry_run and _in_cooldown(rule, now):
            status = "cooldown"
        else:
            # SAVEPOINT: a broken rule rolls back to the event state without
            # harming the triggering operation or sibling rules
            nested = db.begin_nested()
            try:
                for action in rule.actions or []:
                    if dry_run:
                        executed.append({"type": action.get("type"), "dry_run": True})
                    else:
                        executed.append(_execute_action(db, rule, action, payload))
                nested.commit()
                status = "dry_run" if dry_run else "matched"
            except Exception as exc:  # noqa: BLE001 — audit, never propagate
                nested.rollback()
                status, executed, error = "failed", [], str(exc)[:1000]

        run = m.AutomationRun(
            rule_id=rule.id, event_type=event_type, event_row_id=event_row_id,
            status=status, conditions_result=conditions_result,
            actions_executed=executed, error=error,
        )
        db.add(run)

        if status == "matched":
            rule.match_count = (rule.match_count or 0) + 1
            rule.last_matched_at = now
        db.flush()

        summary: dict[str, Any] = {"rule_id": rule.id, "rule": rule.name, "status": status}
        if executed:
            summary["actions"] = executed
        if error:
            summary["error"] = error[:200]
        results.append(summary)

        if status == "matched":
            bus.publish(db, "automation.rule_matched", {
                "rule_id": rule.id, "rule_name": rule.name,
                "event_type": event_type, "actions": [a.get("type") for a in executed],
            })
    return results


def register_dispatcher() -> None:
    """Hook the engine onto every event in the catalog (called once at startup)."""
    from app.core import events as bus

    def make_handler(evt: str):
        def handler(db: Session, payload: dict) -> None:
            handle_event(db, evt, payload)
        return handler

    for event in EVENT_CATALOG:
        bus.subscribe(event["name"], make_handler(event["name"]))


# --------------------------------------------------------------------------
# Serialization + starter rules
# --------------------------------------------------------------------------

def serialize_rule(rule: m.AutomationRule) -> dict:
    return {
        "id": rule.id, "org_id": rule.org_id, "name": rule.name,
        "description": rule.description, "event_type": rule.event_type,
        "enabled": bool(rule.enabled), "conditions": rule.conditions or [],
        "actions": rule.actions or [], "cooldown_seconds": rule.cooldown_seconds,
        "match_count": rule.match_count or 0,
        "last_matched_at": rule.last_matched_at.isoformat() if rule.last_matched_at else None,
        "created_by": rule.created_by,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
    }


def serialize_run(run: m.AutomationRun, rule_name: str = "") -> dict:
    return {
        "id": run.id, "rule_id": run.rule_id, "rule_name": rule_name,
        "event_type": run.event_type, "status": run.status,
        "conditions_result": run.conditions_result or [],
        "actions_executed": run.actions_executed or [],
        "error": run.error,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


STARTER_RULES: list[dict[str, Any]] = [
    {
        "name": "Delivered COD order -> open settlement draft",
        "description": (
            "Capture on delivery is automatic (deterministic subscriber). This rule "
            "opens a §27 draft run from the fresh payables so money starts moving "
            "without waiting for a finance review cycle."
        ),
        "event_type": "order.status_changed",
        "conditions": [{"path": "to", "op": "eq", "value": "delivered"}],
        "actions": [
            {"type": "notify", "category": "finance", "level": "info",
             "title": "Order #{{order_id}} delivered",
             "body": "COD collection handled by the engine; a settlement draft was opened automatically."},
            {"type": "create_settlement_draft"},
        ],
        "cooldown_seconds": 3600,
    },
    {
        "name": "RMA requested -> alert the ops floor",
        "description": (
            "A return request is a customer-trust event: escalate immediately so an "
            "agent reviews the RMA queue inside the 7-day window."
        ),
        "event_type": "return.requested",
        "conditions": [],
        "actions": [
            {"type": "escalate", "category": "returns",
             "title": "New return request {{rma_number}}",
             "body": "Order #{{order_id}} — reason: {{reason}}. Review the RMA queue and approve or reject."},
        ],
        "cooldown_seconds": 0,
    },
    {
        "name": "Negative stock adjustment -> flag for review",
        "description": (
            "Stock shrinking outside sales (damage, miscount, shrinkage) deserves a "
            "second look. Flags every negative warehouse adjustment as a warning."
        ),
        "event_type": "warehouse.stock_adjusted",
        "conditions": [{"path": "delta", "op": "lt", "value": 0}],
        "actions": [
            {"type": "notify", "category": "warehouse", "level": "warning",
             "title": "Stock loss at warehouse {{warehouse_id}}",
             "body": "Product {{product_id}} adjusted by {{delta}} ({{on_hand}} on hand now). Reason is on the movement — verify against the ledger."},
        ],
        "cooldown_seconds": 0,
    },
]
