"""Procurement event wiring — Stock Prophet runs become reorder suggestions.

The demand forecaster is advisory (its `apply` is None), so the bridge from
"AI said reorder X" to "procurement can act on X" lives here: when a
demand_forecaster run succeeds, its output is materialised as
ReorderSuggestions and a `reorder.suggested` event fires (§39 picks it up).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai_harness import models as aim
from app.core import events
from app.procurement import service as svc


def _on_ai_run_completed(db: Session, payload: dict) -> None:
    if payload.get("code") != "demand_forecaster":
        return
    run = db.get(aim.AiRun, payload.get("run_id")) if payload.get("run_id") else None
    if run is None or run.status != "succeeded":
        return
    try:
        svc.sync_suggestions_from_run(db, run)
    except Exception:  # noqa: BLE001 — suggestions must never break the harness
        import traceback

        print(f"[procurement] suggestion sync failed:\n{traceback.format_exc()}")


def register() -> None:
    events.subscribe("ai.run.completed", _on_ai_run_completed)
