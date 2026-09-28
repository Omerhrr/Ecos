"""Notification center API (plan §39).

Every authenticated user reads and manages THEIR OWN notifications — no
module permission needed. Preferences live here too; the dispatcher
already honours them, so muting a category takes effect immediately.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import AuthContext, require_auth
from app.notifications import models as m
from app.notifications import service as svc

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _own(db: Session, ctx: AuthContext):
    return (
        db.query(m.Notification)
        .filter(m.Notification.recipient_user_id == ctx.user.id)
    )


@router.get("")
def list_notifications(
    unread_only: bool = False,
    category: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_auth),
):
    q = _own(db, ctx).order_by(m.Notification.id.desc())
    if unread_only:
        q = q.filter(m.Notification.read_at.is_(None))
    if category:
        q = q.filter(m.Notification.category == category)
    return [svc.serialize(n) for n in q.limit(min(limit, 200)).all()]


@router.get("/unread-count")
def unread_count(db: Session = Depends(get_db), ctx: AuthContext = Depends(require_auth)):
    count = (
        _own(db, ctx)
        .filter(m.Notification.read_at.is_(None))
        .count()
    )
    return {"unread": count}


@router.post("/read-all")
def read_all(db: Session = Depends(get_db), ctx: AuthContext = Depends(require_auth)):
    unread = (
        _own(db, ctx)
        .filter(m.Notification.read_at.is_(None))
        .all()
    )
    marked = svc.mark_read(db, unread)
    db.commit()
    return {"marked": marked}


@router.post("/{notification_id}/read")
def mark_one(
    notification_id: int,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_auth),
):
    n = db.get(m.Notification, notification_id)
    if not n or n.recipient_user_id != ctx.user.id:
        raise HTTPException(404, "Notification not found")
    svc.mark_read(db, [n])
    db.commit()
    return svc.serialize(n)


@router.get("/preferences")
def get_preferences(db: Session = Depends(get_db), ctx: AuthContext = Depends(require_auth)):
    prefs = svc.ensure_preferences(db, ctx.user.id)
    db.commit()
    return [svc.serialize_preference(p) for p in prefs]


class PreferenceIn(BaseModel):
    category: str
    in_app: bool | None = None
    email: bool | None = None
    whatsapp: bool | None = None


@router.put("/preferences")
def put_preference(
    payload: PreferenceIn,
    db: Session = Depends(get_db),
    ctx: AuthContext = Depends(require_auth),
):
    if payload.category not in m.NOTIFICATION_CATEGORIES:
        raise HTTPException(400, f"Unknown category: {payload.category}")
    svc.ensure_preferences(db, ctx.user.id)
    pref = (
        db.query(m.NotificationPreference)
        .filter(
            m.NotificationPreference.user_id == ctx.user.id,
            m.NotificationPreference.category == payload.category,
        )
        .first()
    )
    if payload.in_app is not None:
        pref.in_app = payload.in_app
    if payload.email is not None:
        pref.email = payload.email
    if payload.whatsapp is not None:
        pref.whatsapp = payload.whatsapp
    db.commit()
    return svc.serialize_preference(pref)


@router.post("/test", status_code=201)
def send_test(db: Session = Depends(get_db), ctx: AuthContext = Depends(require_auth)):
    """Drop a demo notification into your own feed — handy for wiring up UI."""
    n = svc.notify_user(
        db, user_id=ctx.user.id, org_id=ctx.user.org_id, category="system",
        level="info", title="Test notification",
        body=f"Hello {ctx.user.name} — the §39 notification center is live.",
        entity_type="test", entity_id=ctx.user.id,
    )
    db.commit()
    return svc.serialize(n)
