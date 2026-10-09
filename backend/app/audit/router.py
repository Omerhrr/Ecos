from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.audit import service as audit_service
from app.core.database import get_db
from app.core.deps import require_perm

router = APIRouter(
    prefix="/audit", tags=["audit"],
    dependencies=[Depends(require_perm("audit:read"))],
)


@router.get("")
def list_audit(
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    actor_user_id: int | None = None,
    source: str | None = None,
    include_http: bool = False,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    """§44 audit trail — who did what, when, to what, with before/after."""
    rows = audit_service.query(
        db, entity_type=entity_type, entity_id=entity_id, action=action,
        actor_user_id=actor_user_id, source=source,
        exclude_http=not include_http, limit=limit,
    )
    return [audit_service.serialize(r) for r in rows]


@router.get("/actions")
def audited_actions():
    """The semantic actions the depth layer knows how to record."""
    return {"actions": audit_service.AUDITED_ACTIONS}
