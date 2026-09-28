"""Automation Engine API (plan §41) — rules CRUD + match audit + replay."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.automation import models as m
from app.automation import service
from app.core.database import get_db
from app.core.deps import AuthContext, require_perm
from app.core.events import publish

router = APIRouter(
    prefix="/automation", tags=["automation"],
    dependencies=[Depends(require_perm("automation:read"))],
)


class ConditionIn(BaseModel):
    path: str = Field(min_length=1, max_length=200)
    op: str = Field(min_length=1, max_length=20)
    value: object = None


class ActionIn(BaseModel):
    type: str
    title: str | None = None
    body: str | None = None
    level: str | None = None
    category: str | None = None
    reason: str | None = None
    product_id: int | None = None
    product_path: str | None = None


class RuleIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = ""
    event_type: str = Field(min_length=3, max_length=100)
    enabled: bool = True
    conditions: list[ConditionIn] = []
    actions: list[ActionIn] = Field(min_length=1)
    cooldown_seconds: int = Field(default=0, ge=0, le=86400 * 7)


class RulePatch(BaseModel):
    name: str | None = None
    description: str | None = None
    enabled: bool | None = None
    conditions: list[ConditionIn] | None = None
    actions: list[ActionIn] | None = None
    cooldown_seconds: int | None = Field(default=None, ge=0, le=86400 * 7)


class ReplayIn(BaseModel):
    event_type: str
    payload: dict = {}


def _load_rule(db: Session, rule_id: int) -> m.AutomationRule:
    rule = db.get(m.AutomationRule, rule_id)
    if rule is None:
        raise HTTPException(404, "Rule not found")
    return rule


def _validate_rule_in(payload: RuleIn) -> None:
    if payload.event_type not in service.EVENT_LABELS:
        raise HTTPException(422, f"Unknown event_type '{payload.event_type}' — see GET /automation/events")
    for c in payload.conditions:
        if c.op not in ("eq", "ne", "gt", "gte", "lt", "lte", "contains", "in", "not_in", "exists", "truthy"):
            raise HTTPException(422, f"Unknown condition op '{c.op}'")
    for a in payload.actions:
        if a.type not in m.ACTION_TYPES:
            raise HTTPException(422, f"Unknown action type '{a.type}' — allowed: {m.ACTION_TYPES}")


@router.get("/events")
def event_catalog():
    """Every subscribable event + a sample payload for the rule builder."""
    return service.EVENT_CATALOG


@router.get("/rules")
def list_rules(db: Session = Depends(get_db)):
    return [service.serialize_rule(r) for r in db.query(m.AutomationRule).order_by(m.AutomationRule.id.asc()).all()]


@router.post("/rules", status_code=201, dependencies=[Depends(require_perm("automation:write"))])
def create_rule(
    payload: RuleIn,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_perm("automation:write")),
):
    _validate_rule_in(payload)
    rule = m.AutomationRule(
        org_id=ctx.user.org_id, name=payload.name, description=payload.description[:1024],
        event_type=payload.event_type, enabled=int(payload.enabled),
        conditions=[c.model_dump() for c in payload.conditions],
        actions=[a.model_dump(exclude_none=True) for a in payload.actions],
        cooldown_seconds=payload.cooldown_seconds, created_by=ctx.user.id,
    )
    db.add(rule)
    db.flush()
    publish(db, "automation.rule_created", {"rule_id": rule.id, "name": rule.name,
                                            "event_type": rule.event_type, "by": ctx.user.id})
    db.commit()
    return service.serialize_rule(rule)


@router.patch("/rules/{rule_id}", dependencies=[Depends(require_perm("automation:write"))])
def patch_rule(rule_id: int, payload: RulePatch, db: Session = Depends(get_db)):
    rule = _load_rule(db, rule_id)
    if payload.name is not None:
        rule.name = payload.name[:120]
    if payload.description is not None:
        rule.description = payload.description[:1024]
    if payload.enabled is not None:
        rule.enabled = int(payload.enabled)
    if payload.conditions is not None:
        rule.conditions = [c.model_dump() for c in payload.conditions]
    if payload.actions is not None:
        if not payload.actions:
            raise HTTPException(422, "A rule needs at least one action")
        for a in payload.actions:
            if a.type not in m.ACTION_TYPES:
                raise HTTPException(422, f"Unknown action type '{a.type}'")
        rule.actions = [a.model_dump(exclude_none=True) for a in payload.actions]
    if payload.cooldown_seconds is not None:
        rule.cooldown_seconds = payload.cooldown_seconds
    db.commit()
    return service.serialize_rule(rule)


@router.delete("/rules/{rule_id}", status_code=204, dependencies=[Depends(require_perm("automation:write"))])
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = _load_rule(db, rule_id)
    db.delete(rule)
    db.commit()


@router.post("/rules/{rule_id}/test")
def test_rule(rule_id: int, payload: ReplayIn, db: Session = Depends(get_db)):
    """Dry-run one rule against a sample payload — evaluates conditions,
    lists would-be actions, writes a `dry_run` audit row, mutates nothing."""
    rule = _load_rule(db, rule_id)
    if payload.event_type != rule.event_type:
        raise HTTPException(422, f"This rule watches '{rule.event_type}', not '{payload.event_type}'")
    results = service.handle_event(db, payload.event_type, payload.payload,
                                   dry_run=True)
    db.commit()
    mine = [r for r in results if r["rule_id"] == rule.id]
    return {"rule_id": rule.id, "results": mine or [{"rule_id": rule.id, "status": "condition_not_met",
                                                     "note": "rule evaluated but not matched (disabled at test time?)"}]}


@router.post("/events/replay", dependencies=[Depends(require_perm("automation:write"))])
def replay_event(payload: ReplayIn, db: Session = Depends(get_db)):
    """Push a synthetic event through the engine FOR REAL (rules fire, actions run).

    Deliberately does NOT publish to the domain bus — domain subscribers
    (COD capture, ledger, notifications...) are not triggered; only
    automation rules see this event. Audit rows land in automation_runs.
    """
    if payload.event_type not in service.EVENT_LABELS:
        raise HTTPException(422, f"Unknown event_type '{payload.event_type}'")
    results = service.handle_event(db, payload.event_type, payload.payload)
    db.commit()
    return {"event_type": payload.event_type, "results": results}


@router.get("/runs")
def list_runs(rule_id: int | None = None, status: str | None = None, limit: int = 50,
              db: Session = Depends(get_db)):
    q = db.query(m.AutomationRun).order_by(m.AutomationRun.id.desc())
    if rule_id:
        q = q.filter(m.AutomationRun.rule_id == rule_id)
    if status:
        q = q.filter(m.AutomationRun.status == status)
    runs = q.limit(min(limit, 200)).all()
    names = {r.id: r.name for r in db.query(m.AutomationRule).all()}
    return [service.serialize_run(r, names.get(r.rule_id, f"rule {r.rule_id}")) for r in runs]
