"""In-process domain event bus (plan §40).

Events are persisted to the `domain_events` table (audit trail) and dispatched
to registered subscribers within the same database transaction, so handlers
participate atomically with the triggering operation.

Deterministic automation lives in subscribers (plan §41): e.g. a delivered
COD order automatically collects payment and writes ledger entries.
"""

from __future__ import annotations

import traceback
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.models import DomainEvent

# handler signature: handler(db: Session, payload: dict) -> None
_subscribers: dict[str, list[Callable[..., None]]] = {}


def subscribe(event_name: str, handler: Callable[..., None]) -> None:
    _subscribers.setdefault(event_name, []).append(handler)


def publish(db: Session, event_name: str, payload: dict[str, Any]) -> DomainEvent:
    """Persist an event and synchronously notify subscribers."""
    row = DomainEvent(name=event_name, payload=payload)
    db.add(row)
    db.flush()
    for handler in _subscribers.get(event_name, []):
        try:
            handler(db, payload)
        except Exception:  # noqa: BLE001 — one failing handler must not kill the flow
            print(f"[events] subscriber error on {event_name}:\n{traceback.format_exc()}")
    return row
