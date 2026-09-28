from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_perm
from app.settlements import models as m
from app.settlements import service

router = APIRouter(
    prefix="/settlements", tags=["settlements"],
    dependencies=[Depends(require_perm("settlements:read"))],
)


class BuildRunBody(BaseModel):
    note: str = ""
    order_ids: list[int] | None = None


@router.get("/preview")
def preview(order_ids: str | None = None, db: Session = Depends(get_db)):
    """What a new settlement run would capture right now (§27)."""
    ids = [int(x) for x in order_ids.split(",") if x.strip().isdigit()] if order_ids else None
    return service.unsettled_summary(db, order_ids=ids)


@router.get("")
def list_runs(db: Session = Depends(get_db)):
    runs = db.query(m.SettlementRun).order_by(m.SettlementRun.id.desc()).limit(100).all()
    return [service.serialize_run(db, r) for r in runs]


@router.post("", status_code=201, dependencies=[Depends(require_perm("settlements:write"))])
def build(body: BuildRunBody, db: Session = Depends(get_db)):
    try:
        run = service.build_run(db, note=body.note, order_ids=body.order_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    db.commit()
    return service.serialize_run(db, run, with_lines=True)


@router.get("/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(m.SettlementRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Settlement run not found")
    return service.serialize_run(db, run, with_lines=True)


def _load(db: Session, run_id: int) -> m.SettlementRun:
    run = db.get(m.SettlementRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Settlement run not found")
    return run


@router.post("/{run_id}/approve", dependencies=[Depends(require_perm("settlements:write"))])
def approve(run_id: int, db: Session = Depends(get_db)):
    run = service.approve_run(db, _load(db, run_id))
    db.commit()
    return service.serialize_run(db, run, with_lines=True)


@router.post("/{run_id}/execute", dependencies=[Depends(require_perm("settlements:write"))])
def execute(run_id: int, db: Session = Depends(get_db)):
    run = service.execute_run(db, _load(db, run_id))
    db.commit()
    return service.serialize_run(db, run, with_lines=True)


@router.post("/{run_id}/cancel", dependencies=[Depends(require_perm("settlements:write"))])
def cancel(run_id: int, db: Session = Depends(get_db)):
    run = service.cancel_run(db, _load(db, run_id))
    db.commit()
    return service.serialize_run(db, run, with_lines=True)
