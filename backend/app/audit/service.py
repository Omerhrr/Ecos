"""Audit service (plan §44).

`record()` is deliberately exception-safe: an audit failure must NEVER break
the business operation it is observing. Snapshots are plain dicts; anything
JSON-unserializable is stringified so a record always lands.
"""

from __future__ import annotations

import json
import traceback
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.core.deps import AuthContext

AUDITED_ACTIONS: list[str] = [
    # catalog
    "product.created", "product.updated", "product.price_changed",
    "product.variant_created", "product.variant_updated",
    # money
    "payment.captured", "payment.refunded", "finance.fx_rate_updated",
    # settlements
    "settlement.built", "settlement.approved", "settlement.executed", "settlement.cancelled",
    # governance
    "ai.run_approved", "ai.settings_changed",
    # corridor gates (Luxeen review, §8)
    "market.product_reviewed", "market.product_published", "market.supplier_org_provisioned",
    # identity
    "identity.user_created", "identity.org_provisioned",
    # economics config (§57)
    "finance.profile_created", "finance.profile_updated",
    # logistics config (§21)
    "logistics.rate_card_created", "logistics.rate_card_updated",
]

_HTTP_ACTION = "http.request"


def _safe(value: Any, limit: int = 4000) -> Any:
    """Make any value JSON-safe and size-bounded."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)[:limit]


def _snapshot(obj: Any) -> dict | None:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {k: _safe(v) for k, v in obj.items()}
    if hasattr(obj, "__dict__"):
        return {
            k: _safe(v)
            for k, v in vars(obj).items()
            if not k.startswith("_") and k not in {"password_hash"}
        }
    return {"value": _safe(obj)}


def diff(before: dict | None, after: dict | None, only: list[str] | None = None) -> dict:
    """Minimal changed-fields map: {field: {"from": old, "to": new}}."""
    if not before or not after:
        return {}
    keys = set(before) & set(after) if only is None else set(only)
    out: dict = {}
    for k in sorted(keys):
        old, new = before.get(k), after.get(k)
        if old != new:
            out[k] = {"from": _safe(old, 500), "to": _safe(new, 500)}
    return out


def record(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: Any = "",
    ctx: AuthContext | None = None,
    before: Any = None,
    after: Any = None,
    changed_only: list[str] | None = None,
    source: str = "api",
    request: Request | None = None,
    method: str = "",
    path: str = "",
    auth_context: str = "",
) -> AuditLog | None:
    """Write one audit row. Never raises — audit must not break business flow."""
    try:
        before_snap = _snapshot(before)
        after_snap = _snapshot(after)
        changed = diff(before_snap, after_snap, changed_only)
        if before_snap is not None or after_snap is not None:
            after_snap = {k: v for k, v in (after_snap or {}).items() if k not in changed} or after_snap

        ip, req_method, req_path = "", method, path
        if request is not None:
            try:
                ip = request.client.host if request.client else ""
                req_method = request.method
                req_path = request.url.path
            except Exception:  # noqa: BLE001
                pass

        row = AuditLog(
            org_id=ctx.org.id if ctx and ctx.org else None,
            actor_user_id=ctx.user.id if ctx and ctx.user else None,
            actor_label=(ctx.user.email if ctx and ctx.user else "system"),
            actor_role=ctx.role if ctx else "system",
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id or ""),
            before=json.dumps(before_snap) if before_snap is not None else None,
            after=json.dumps(after_snap) if after_snap is not None else None,
            changed=json.dumps(changed) if changed else None,
            source=source,
            method=req_method,
            path=req_path,
            ip=ip,
            auth_context=auth_context or (ctx.role if ctx else ""),
        )
        db.add(row)
        db.flush()
        return row
    except Exception:  # noqa: BLE001 — audit must never break the caller
        print("[audit] record failed:\n" + traceback.format_exc())
        return None


def record_http(db: Session, *, request: Request, status_code: int,
                token_payload: dict | None) -> None:
    """Blanket layer: one row per mutating request (§44 source coverage)."""
    try:
        payload = token_payload or {}
        sub = payload.get("sub")
        row = AuditLog(
            org_id=None,
            actor_user_id=int(sub) if sub else None,
            actor_label=f"user:{sub}" if sub else "anonymous",
            actor_role=payload.get("role", ""),
            action=_HTTP_ACTION,
            entity_type="http",
            entity_id=f"{request.method} {request.url.path}",
            source="http",
            method=request.method,
            path=request.url.path,
            ip=request.client.host if request.client else "",
            auth_context=f"status={status_code}",
        )
        db.add(row)
        db.commit()
    except Exception:  # noqa: BLE001
        print("[audit] http record failed:\n" + traceback.format_exc())


def serialize(row: AuditLog) -> dict:
    def _load(raw: str | None) -> dict | None:
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return {"raw": raw}

    return {
        "id": row.id,
        "org_id": row.org_id,
        "actor_user_id": row.actor_user_id,
        "actor_label": row.actor_label,
        "actor_role": row.actor_role,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "before": _load(row.before),
        "after": _load(row.after),
        "changed": _load(row.changed),
        "source": row.source,
        "method": row.method,
        "path": row.path,
        "ip": row.ip,
        "auth_context": row.auth_context,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def query(
    db: Session,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    actor_user_id: int | None = None,
    source: str | None = None,
    exclude_http: bool = True,
    limit: int = 200,
) -> list[AuditLog]:
    q = db.query(AuditLog).order_by(AuditLog.id.desc())
    if entity_type:
        q = q.filter(AuditLog.entity_type == entity_type)
    if entity_id:
        q = q.filter(AuditLog.entity_id == str(entity_id))
    if action:
        q = q.filter(AuditLog.action == action)
    if actor_user_id:
        q = q.filter(AuditLog.actor_user_id == actor_user_id)
    if source:
        q = q.filter(AuditLog.source == source)
    # the blanket layer's rows are noise by default — unless the caller
    # explicitly asks for them by action
    if exclude_http and action != _HTTP_ACTION:
        q = q.filter(AuditLog.action != _HTTP_ACTION)
    return q.limit(min(limit, 500)).all()
