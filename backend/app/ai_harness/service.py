"""AI Harness service (plan §31, §37-38).

Run loop:
    1. operator + params -> blueprint.gather(db, params)   (live Ecos state)
    2. messages = [system: role + task_brief + heuristic hint,
                   user: context JSON + instruction]
    3. llm.chat(json_mode=True)  -> DeepSeek, or deterministic fallback
    4. parse output -> AiRun persisted with full audit fields
    5. events.publish("ai.run.completed")

Governance (§37-38): any blueprint with `apply` side effects stays
`proposal_status="pending"` until a human with ai_harness:approve calls
approve/reject. approve() executes the side effect and marks `applied`.
Advisory blueprints (no apply) are marked "advisory" immediately.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.ai_harness import models as m
from app.ai_harness import operators as ops
from app.core import events
from app.core import llm


def parse_output(content: str) -> dict[str, Any]:
    """Model output -> dict (tolerates code fences / stray prose)."""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {"result": data}
    except json.JSONDecodeError:
        block = ops._extract_json_block(text)  # noqa: SLF001 — shared helper
        if block:
            return json.loads(block)
        raise ValueError("Model did not return parseable JSON")


def _messages(operator: m.AiOperator, context: dict[str, Any], heuristic_payload: dict[str, Any]) -> list[dict[str, str]]:
    blueprint = ops.BLUEPRINTS[operator.code]
    system = (
        f"{operator.role_description}\n\n"
        f"{blueprint['task_brief']}\n\n"
        f"[[HEURISTIC]] {json.dumps(heuristic_payload, ensure_ascii=False)}"
    )
    user = (
        "LIVE ECOS CONTEXT (authoritative data):\n"
        f"{json.dumps(context, ensure_ascii=False, default=str)}\n\n"
        "Produce the JSON response now."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def run_operator(db: Session, operator: m.AiOperator, params: dict[str, Any], *, actor: dict) -> m.AiRun:
    if operator.status != "active":
        raise ValueError(f"Operator {operator.name} is {operator.status}; activate it first")
    blueprint = ops.BLUEPRINTS[operator.code]

    context = blueprint["gather"](db, params)  # may raise ValueError -> failed run
    run = m.AiRun(
        operator_id=operator.id, org_id=operator.org_id,
        status="failed", input=dict(params), output={}, error="",
        proposal_status="advisory" if blueprint["advisory"] else "pending",
    )
    db.add(run)
    db.flush()

    try:
        messages = _messages(operator, context, blueprint["heuristic"](context))
        result = llm.chat(messages, json_mode=True)
        output = parse_output(result["content"])
        # internal references the apply() step needs, prefixed to stay out of UI prose
        for key, value in context.items():
            if isinstance(value, dict) and "id" in value:
                output[f"_{key}_id"] = value["id"]
        run.status = "succeeded"
        run.output = output
        run.provider = result["provider"]
        run.model = result["model"]
        run.prompt_tokens = result["prompt_tokens"]
        run.completion_tokens = result["completion_tokens"]
        run.latency_ms = result["latency_ms"]
        db.flush()
        events.publish(db, "ai.run.completed", {
            "run_id": run.id, "operator_id": operator.id, "operator": operator.name,
            "code": operator.code, "provider": run.provider,
            "proposal_status": run.proposal_status,
            "latency_ms": run.latency_ms,
        })
    except Exception as exc:  # noqa: BLE001 — harness records its own failures
        run.status = "failed"
        run.error = str(exc)[:2000]
        db.flush()
        events.publish(db, "ai.run.failed", {
            "run_id": run.id, "operator_id": operator.id,
            "operator": operator.name, "error": run.error[:300],
        })
    return run


def approve_run(db: Session, run: m.AiRun, *, actor: dict) -> m.AiRun:
    if run.status != "succeeded" or run.proposal_status != "pending":
        raise ValueError("Only successful pending proposals can be approved")
    operator = db.get(m.AiOperator, run.operator_id)
    blueprint = ops.BLUEPRINTS[operator.code]
    if blueprint.get("apply") is None:
        raise ValueError("This operator is advisory — nothing to approve")

    applied = blueprint["apply"](db, operator, run.output, actor)  # may raise
    run.output = {**run.output, "applied": applied}
    run.proposal_status = "applied"
    run.approved_by = actor.get("user_id")
    run.approved_at = datetime.now(timezone.utc)
    db.flush()
    events.publish(db, "ai.proposal.approved", {
        "run_id": run.id, "operator_id": operator.id, "operator": operator.name,
        "approved_by": actor.get("user_id"), "applied": applied,
    })
    return run


def reject_run(db: Session, run: m.AiRun, *, actor: dict, note: str = "") -> m.AiRun:
    if run.proposal_status != "pending":
        raise ValueError("Only pending proposals can be rejected")
    run.proposal_status = "rejected"
    run.approved_by = actor.get("user_id")
    run.approved_at = datetime.now(timezone.utc)
    if note:
        run.output = {**run.output, "rejection_note": note}
    db.flush()
    events.publish(db, "ai.proposal.rejected", {
        "run_id": run.id, "operator_id": run.operator_id, "note": note[:200],
    })
    return run


def deploy_operator(db: Session, *, code: str, org_id: int | None, actor: dict) -> m.AiOperator:
    if code not in ops.BLUEPRINTS:
        raise ValueError(f"Unknown operator blueprint: {code}")
    # Idempotent deploy: an org runs exactly one operator per blueprint code.
    # Re-deploying (API retry, smoke, ensure-backfill) returns the existing row.
    if org_id is not None:
        existing = (
            db.query(m.AiOperator)
            .filter(m.AiOperator.org_id == org_id, m.AiOperator.code == code)
            .first()
        )
        if existing is not None:
            return existing
    blueprint = ops.BLUEPRINTS[code]
    operator = m.AiOperator(
        org_id=org_id, code=code, name=blueprint["name"],
        role_description=blueprint["role_description"],
        system_prompt=blueprint["task_brief"],
        autonomy="act_with_approval", status="active",
    )
    db.add(operator)
    db.flush()
    events.publish(db, "ai.operator.deployed", {
        "operator_id": operator.id, "code": code, "name": operator.name,
        "deployed_by": actor.get("user_id"),
    })
    return operator


def ensure_operators_deployed(db: Session) -> list[m.AiOperator]:
    """Backfill: deploy any blueprint an org doesn't run yet (§31-38 bench).

    Called at startup after seeding, so orgs that already adopted the
    harness gain newly built operators without a manual deploy. Orgs that
    never deployed anything are left untouched.
    """
    created: list[m.AiOperator] = []
    org_ids = [
        row[0] for row in db.query(m.AiOperator.org_id).distinct().all() if row[0] is not None
    ]
    for org_id in org_ids:
        existing = {
            row[0] for row in db.query(m.AiOperator.code).filter(m.AiOperator.org_id == org_id).all()
        }
        for code in ops.BLUEPRINTS:
            if code not in existing:
                created.append(deploy_operator(db, code=code, org_id=org_id, actor={"user_id": None}))
    return created


def serialize_operator(db: Session, operator: m.AiOperator) -> dict[str, Any]:
    last_run = (
        db.query(m.AiRun)
        .filter(m.AiRun.operator_id == operator.id)
        .order_by(m.AiRun.id.desc())
        .first()
    )
    pending = (
        db.query(m.AiRun)
        .filter(m.AiRun.operator_id == operator.id, m.AiRun.proposal_status == "pending")
        .count()
    )
    blueprint = ops.BLUEPRINTS.get(operator.code, {})
    return {
        "id": operator.id, "org_id": operator.org_id, "code": operator.code,
        "name": operator.name, "role_description": operator.role_description,
        "autonomy": operator.autonomy, "status": operator.status,
        "input_fields": blueprint.get("input_fields", []),
        "advisory": blueprint.get("advisory", False),
        "runs_total": db.query(m.AiRun).filter(m.AiRun.operator_id == operator.id).count(),
        "runs_pending": pending,
        "last_run_id": last_run.id if last_run else None,
        "last_run_status": last_run.status if last_run else None,
        "last_run_at": last_run.created_at.isoformat() if last_run else None,
        "created_at": operator.created_at.isoformat() if operator.created_at else None,
    }


def serialize_run(db: Session, run: m.AiRun) -> dict[str, Any]:
    operator = db.get(m.AiOperator, run.operator_id)
    return {
        "id": run.id, "operator_id": run.operator_id,
        "operator_name": operator.name if operator else None,
        "operator_code": operator.code if operator else None,
        "status": run.status, "proposal_status": run.proposal_status,
        "input": run.input, "output": run.output, "error": run.error,
        "provider": run.provider, "model": run.model,
        "prompt_tokens": run.prompt_tokens, "completion_tokens": run.completion_tokens,
        "latency_ms": run.latency_ms,
        "approved_by": run.approved_by,
        "approved_at": run.approved_at.isoformat() if run.approved_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }
