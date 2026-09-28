"""Notification center service (plan §39).

`notify()` is the single fan-out point: domain subscribers call it with an
org scope and it materialises one in-app row per active user of that org,
skipping users who muted the category in their preferences. Channel rows
(email / whatsapp) are recorded on the preference so Phase 3 outbound
workers can replay the same dispatch decisions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.identity import models as im
from app.notifications import models as m
from app.notifications import outbound


def _active_users(db: Session, org_id: int) -> list[im.User]:
    return (
        db.query(im.User)
        .filter(im.User.org_id == org_id, im.User.is_active.is_(True))
        .all()
    )


def _enqueue_channels(
    db: Session, *, user: im.User, pref: m.NotificationPreference | None,
    category: str, title: str, body: str, org_id: int | None,
    notification_id: int | None,
) -> None:
    """§39 Phase 3 — queue email/WhatsApp deliveries for opted-in users."""
    if pref is None:
        return
    targets: list[tuple[str, str]] = []
    if pref.email and user.email:
        targets.append(("email", user.email))
    if pref.whatsapp and user.phone:
        targets.append(("whatsapp", user.phone))
    for channel, recipient in targets:
        outbound.enqueue(
            db, user_id=user.id, org_id=org_id, channel=channel,
            recipient=recipient, category=category, subject=title,
            body=body, notification_id=notification_id,
        )


def notify(
    db: Session,
    *,
    org_id: int | None,
    category: str,
    level: str = "info",
    title: str,
    body: str = "",
    entity_type: str = "",
    entity_id: int | None = None,
    meta: dict[str, Any] | None = None,
) -> list[m.Notification]:
    """Fan a notification out to every active user of `org_id`.

    Users with `in_app=False` for `category` are skipped (§39 preferences).
    Safe to call inside any transaction — it only adds rows.
    """
    if org_id is None:
        return []
    created: list[m.Notification] = []
    for user in _active_users(db, org_id):
        pref = (
            db.query(m.NotificationPreference)
            .filter(
                m.NotificationPreference.user_id == user.id,
                m.NotificationPreference.category == category,
            )
            .first()
        )
        if pref and not pref.in_app:
            continue
        row = m.Notification(
            recipient_user_id=user.id, org_id=org_id, category=category,
            level=level if level in m.NOTIFICATION_LEVELS else "info",
            title=title[:255], body=(body or "")[:1024],
            entity_type=entity_type, entity_id=entity_id, meta=meta or {},
        )
        db.add(row)
        db.flush()
        created.append(row)
        _enqueue_channels(
            db, user=user, pref=pref, category=category, title=title,
            body=body or "", org_id=org_id, notification_id=row.id,
        )
    return created


def notify_user(
    db: Session,
    *,
    user_id: int,
    org_id: int | None,
    category: str = "system",
    level: str = "info",
    title: str,
    body: str = "",
    entity_type: str = "",
    entity_id: int | None = None,
    meta: dict[str, Any] | None = None,
    channels: bool = True,
) -> m.Notification:
    """Direct-to-user notification (bypasses org fan-out)."""
    row = m.Notification(
        recipient_user_id=user_id, org_id=org_id, category=category,
        level=level if level in m.NOTIFICATION_LEVELS else "info",
        title=title[:255], body=(body or "")[:1024],
        entity_type=entity_type, entity_id=entity_id, meta=meta or {},
    )
    db.add(row)
    db.flush()
    if channels:
        user = db.get(im.User, user_id)
        pref = (
            db.query(m.NotificationPreference)
            .filter(
                m.NotificationPreference.user_id == user_id,
                m.NotificationPreference.category == category,
            )
            .first()
        )
        if user is not None:
            _enqueue_channels(
                db, user=user, pref=pref, category=category, title=title,
                body=body or "", org_id=org_id, notification_id=row.id,
            )
    return row


def ensure_preferences(db: Session, user_id: int) -> list[m.NotificationPreference]:
    """Get-or-create the default preference set for a user."""
    existing = {
        p.category
        for p in db.query(m.NotificationPreference)
        .filter(m.NotificationPreference.user_id == user_id)
        .all()
    }
    for cat in m.NOTIFICATION_CATEGORIES:
        if cat not in existing:
            db.add(m.NotificationPreference(user_id=user_id, category=cat))
    db.flush()
    return (
        db.query(m.NotificationPreference)
        .filter(m.NotificationPreference.user_id == user_id)
        .all()
    )


def serialize(n: m.Notification) -> dict[str, Any]:
    return {
        "id": n.id,
        "recipient_user_id": n.recipient_user_id,
        "org_id": n.org_id,
        "category": n.category,
        "level": n.level,
        "title": n.title,
        "body": n.body,
        "entity_type": n.entity_type,
        "entity_id": n.entity_id,
        "meta": n.meta or {},
        "read": n.read_at is not None,
        "read_at": n.read_at.isoformat() if n.read_at else None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


def serialize_preference(p: m.NotificationPreference) -> dict[str, Any]:
    return {
        "category": p.category,
        "in_app": bool(p.in_app),
        "email": bool(p.email),
        "whatsapp": bool(p.whatsapp),
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def mark_read(db: Session, rows: list[m.Notification]) -> int:
    now = datetime.now(timezone.utc)
    count = 0
    for n in rows:
        if n.read_at is None:
            n.read_at = now
            count += 1
    db.flush()
    return count
