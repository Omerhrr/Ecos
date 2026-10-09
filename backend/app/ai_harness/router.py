from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai_harness import models as m
from app.ai_harness import operators as ops
from app.ai_harness import service
from app.audit import service as audit_service
from app.core.database import get_db
from app.core.deps import require_perm, AuthContext
from app.core import llm

router = APIRouter(
    prefix="/ai", tags=["ai-harness"],
    dependencies=[Depends(require_perm("ai_harness:read"))],
)


class DeployBody(BaseModel):
    code: str


class ProviderSettingsBody(BaseModel):
    """§31 key flow — api_key None = keep stored, "" = clear, value = replace."""
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None


class PatchBody(BaseModel):
    status: str | None = None
    system_prompt: str | None = None


class RunBody(BaseModel):
    params: dict = {}


class RejectBody(BaseModel):
    note: str = ""


@router.get("/provider")
def provider():
    """Which brain is the harness running on (§31)?"""
    return llm.provider_info()


@router.post(
    "/provider/test",
    dependencies=[Depends(require_perm("ai_harness:write"))],
)
def provider_test(db: Session = Depends(get_db)):
    """Live DeepSeek ping — 400 with setup instructions when no key is set.
    Outcome is recorded on the provider settings row (§31 key flow)."""
    try:
        result = llm.test_connection()
    except RuntimeError as exc:
        try:
            llm.record_test_result(ok=False, latency_ms=None, error=str(exc))
            db.commit()
        except Exception:  # noqa: BLE001 — recording must never mask the real error
            db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        llm.record_test_result(ok=True, latency_ms=result.get("latency_ms"))
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
    return result


@router.put(
    "/provider/settings",
    dependencies=[Depends(require_perm("ai_harness:write"))],
)
def save_provider_settings(
    body: ProviderSettingsBody,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_perm("ai_harness:write")),
):
    """Store the DeepSeek key/model/base URL (obfuscated at rest) — the
    harness flips to live inference on the very next call, no restart."""
    llm.write_settings(
        api_key=body.api_key, model=body.model, base_url=body.base_url,
        updated_by=ctx.user.id,
    )
    db.commit()
    return llm.provider_info()


@router.get("/registry")
def registry():
    return [
        {
            "code": b["code"], "name": b["name"],
            "role_description": b["role_description"],
            "advisory": b["advisory"], "input_fields": b["input_fields"],
        }
        for b in ops.BLUEPRINTS.values()
    ]


@router.get("/operators")
def list_operators(db: Session = Depends(get_db)):
    operators = db.query(m.AiOperator).order_by(m.AiOperator.id.asc()).all()
    return [service.serialize_operator(db, o) for o in operators]


@router.post(
    "/operators", status_code=201,
    dependencies=[Depends(require_perm("ai_harness:write"))],
)
def deploy_operator(
    body: DeployBody,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_perm("ai_harness:write")),
):
    try:
        operator = service.deploy_operator(
            db, code=body.code, org_id=ctx.user.org_id,
            actor={"user_id": ctx.user.id},
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    db.commit()
    return service.serialize_operator(db, operator)


def _load_operator(db: Session, operator_id: int) -> m.AiOperator:
    operator = db.get(m.AiOperator, operator_id)
    if operator is None:
        raise HTTPException(status_code=404, detail="Operator not found")
    return operator


@router.patch(
    "/operators/{operator_id}",
    dependencies=[Depends(require_perm("ai_harness:write"))],
)
def patch_operator(operator_id: int, body: PatchBody, db: Session = Depends(get_db)):
    operator = _load_operator(db, operator_id)
    if body.status is not None:
        if body.status not in m.OPERATOR_STATUSES:
            raise HTTPException(status_code=422, detail=f"status must be one of {m.OPERATOR_STATUSES}")
        operator.status = body.status
    if body.system_prompt is not None:
        operator.system_prompt = body.system_prompt[:4096]
    db.commit()
    return service.serialize_operator(db, operator)


@router.post(
    "/operators/{operator_id}/run",
    dependencies=[Depends(require_perm("ai_harness:write"))],
)
def run_operator(
    operator_id: int, body: RunBody,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_perm("ai_harness:write")),
):
    operator = _load_operator(db, operator_id)
    run = service.run_operator(
        db, operator, body.params, actor={"user_id": ctx.user.id},
    )
    db.commit()
    return service.serialize_run(db, run)


@router.get("/runs")
def list_runs(operator_id: int | None = None, limit: int = 50, db: Session = Depends(get_db)):
    q = db.query(m.AiRun).order_by(m.AiRun.id.desc())
    if operator_id:
        q = q.filter(m.AiRun.operator_id == operator_id)
    return [service.serialize_run(db, r) for r in q.limit(min(limit, 200)).all()]


def _load_run(db: Session, run_id: int) -> m.AiRun:
    run = db.get(m.AiRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)):
    return service.serialize_run(db, _load_run(db, run_id))


@router.post(
    "/runs/{run_id}/approve",
    dependencies=[Depends(require_perm("ai_harness:approve"))],
)
def approve_run(
    run_id: int,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_perm("ai_harness:approve")),
):
    target = _load_run(db, run_id)
    try:
        run = service.approve_run(db, target, actor={"user_id": ctx.user.id})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    operator = db.get(m.AiOperator, run.operator_id)
    audit_service.record(
        db, ctx=ctx, request=request,
        action="ai.run_approved", entity_type="ai_run", entity_id=run.id,
        before={"proposal_status": target.proposal_status},
        after={"proposal_status": run.proposal_status,
               "operator": operator.code if operator else str(run.operator_id)},
        changed_only=["proposal_status", "approved_by", "approved_at"],
        source="ai", auth_context="ai_harness:approve",
    )
    db.commit()
    return service.serialize_run(db, run)


@router.post(
    "/runs/{run_id}/reject",
    dependencies=[Depends(require_perm("ai_harness:approve"))],
)
def reject_run(
    run_id: int, body: RejectBody,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_perm("ai_harness:approve")),
):
    try:
        run = service.reject_run(
            db, _load_run(db, run_id),
            actor={"user_id": ctx.user.id}, note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    db.commit()
    return service.serialize_run(db, run)
