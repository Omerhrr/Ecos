"""§39 Phase 3 — outbound channel workers (email / WhatsApp).

Outbox pattern: the notification dispatcher enqueues one row per (user,
channel) whose preference switch is on; `process_outbox()` drains due rows
through the channel provider and records the delivery outcome.

Providers are pluggable and env-driven — the same worker code runs in the
demo and in production:
- email     : SMTP (SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS/SMTP_FROM) or
              the `dev-console` provider which logs the message instead of
              sending it, so the flow is observable without credentials.
- whatsapp  : WhatsApp Cloud API (WHATSAPP_TOKEN + WHATSAPP_PHONE_NUMBER_ID)
              or `dev-console`.

Failures retry with exponential backoff (60s * 2^attempts) until
`max_attempts` is exhausted, then the row is marked failed — nothing is
ever silently dropped.
"""

from __future__ import annotations

import os
import smtplib
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.notifications import models as m

RETRY_BASE_SECONDS = 60


# --------------------------------------------------------------------------
# Providers — each returns (provider_name, provider_ref) or raises
# --------------------------------------------------------------------------

def _smtp_config() -> dict[str, str] | None:
    host = os.environ.get("SMTP_HOST")
    if not host:
        return None
    return {
        "host": host,
        "port": os.environ.get("SMTP_PORT", "587"),
        "user": os.environ.get("SMTP_USER", ""),
        "pass": os.environ.get("SMTP_PASS", ""),
        "from": os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", "ecos@localhost")),
    }


def send_email_smtp(recipient: str, subject: str, body: str) -> tuple[str, str]:
    cfg = _smtp_config()
    if cfg is None:
        return send_email_dev_console(recipient, subject, body)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["from"]
    msg["To"] = recipient
    msg.set_content(body)
    with smtplib.SMTP(cfg["host"], int(cfg["port"]), timeout=15) as server:
        try:
            server.starttls()
        except smtplib.SMTPException:
            pass  # plain SMTP (local relays)
        if cfg["user"]:
            server.login(cfg["user"], cfg["pass"])
        server.send_message(msg)
    return "smtp", f"smtp:{uuid.uuid4().hex[:12]}"


def send_email_dev_console(recipient: str, subject: str, body: str) -> tuple[str, str]:
    ref = f"dev-{uuid.uuid4().hex[:12]}"
    print(f"[outbound:email:{ref}] To: {recipient} | Subject: {subject}\n{body}\n")
    return "dev-console", ref


def _whatsapp_config() -> dict[str, str] | None:
    token = os.environ.get("WHATSAPP_TOKEN")
    phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
    if not token or not phone_id:
        return None
    return {"token": token, "phone_id": phone_id}


def send_whatsapp_cloud(recipient: str, subject: str, body: str) -> tuple[str, str]:
    cfg = _whatsapp_config()
    if cfg is None:
        return send_whatsapp_dev_console(recipient, subject, body)
    import httpx

    # Cloud API wants E.164 digits only
    to = "".join(ch for ch in recipient if ch.isdigit())
    resp = httpx.post(
        f"https://graph.facebook.com/v21.0/{cfg['phone_id']}/messages",
        headers={"Authorization": f"Bearer {cfg['token']}"},
        json={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": body[:4096]},
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    ref = (data.get("messages") or [{}])[0].get("id", "")
    return "whatsapp_cloud", ref or f"wa:{uuid.uuid4().hex[:12]}"


def send_whatsapp_dev_console(recipient: str, subject: str, body: str) -> tuple[str, str]:
    ref = f"dev-{uuid.uuid4().hex[:12]}"
    print(f"[outbound:whatsapp:{ref}] To: {recipient} | {subject}\n{body}\n")
    return "dev-console", ref


CHANNEL_SENDERS: dict[str, Callable[[str, str, str], tuple[str, str]]] = {
    "email": send_email_smtp,
    "whatsapp": send_whatsapp_cloud,
}


# --------------------------------------------------------------------------
# Outbox processing
# --------------------------------------------------------------------------

def enqueue(
    db: Session, *, user_id: int, org_id: int | None, channel: str,
    recipient: str, category: str, subject: str, body: str,
    notification_id: int | None = None,
) -> m.NotificationOutbox | None:
    """Queue one outbound message (dispatcher-side)."""
    if channel not in m.OUTBOX_CHANNELS or not recipient:
        return None
    row = m.NotificationOutbox(
        org_id=org_id, user_id=user_id, channel=channel, recipient=recipient[:255],
        category=category, subject=subject[:255], body=body[:4096],
        notification_id=notification_id,
    )
    db.add(row)
    db.flush()
    return row


def process_outbox(db: Session, limit: int = 25) -> dict[str, Any]:
    """Drain due queued rows through their channel worker (one attempt each)."""
    now = datetime.now(timezone.utc)
    due = (
        db.query(m.NotificationOutbox)
        .filter(m.NotificationOutbox.status == "queued", m.NotificationOutbox.available_at <= now)
        .order_by(m.NotificationOutbox.id)
        .limit(min(limit, 100))
        .all()
    )
    sent = failed = retried = 0
    for row in due:
        sender = CHANNEL_SENDERS.get(row.channel)
        row.attempts += 1
        if sender is None:
            row.status = "failed"
            row.last_error = f"No worker registered for channel {row.channel}"
            failed += 1
            continue
        try:
            provider, ref = sender(row.recipient, row.subject, row.body)
            row.status = "sent"
            row.provider = provider
            row.provider_ref = ref
            row.sent_at = datetime.now(timezone.utc)
            row.last_error = ""
            sent += 1
        except Exception as exc:  # noqa: BLE001 — provider errors must not kill the drain
            row.last_error = str(exc)[:1024]
            if row.attempts >= row.max_attempts:
                row.status = "failed"
                failed += 1
            else:
                delay = RETRY_BASE_SECONDS * (2 ** (row.attempts - 1))
                row.available_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
                retried += 1
    db.flush()
    return {"processed": len(due), "sent": sent, "failed": failed, "retried": retried}


def outbox_stats(db: Session) -> dict[str, Any]:
    rows = db.query(m.NotificationOutbox).all()
    by_channel: dict[str, dict[str, int]] = {}
    for r in rows:
        ch = by_channel.setdefault(r.channel, {"queued": 0, "sent": 0, "failed": 0, "total": 0})
        ch["total"] += 1
        if r.status in ch:
            ch[r.status] += 1
    return {
        "providers": {
            "email": _smtp_config() and "smtp" or "dev-console",
            "whatsapp": _whatsapp_config() and "whatsapp_cloud" or "dev-console",
        },
        "by_channel": by_channel,
    }


def serialize_outbox(row: m.NotificationOutbox) -> dict[str, Any]:
    return {
        "id": row.id,
        "org_id": row.org_id,
        "user_id": row.user_id,
        "channel": row.channel,
        "recipient": row.recipient,
        "category": row.category,
        "subject": row.subject,
        "body": row.body,
        "notification_id": row.notification_id,
        "status": row.status,
        "attempts": row.attempts,
        "max_attempts": row.max_attempts,
        "provider": row.provider,
        "provider_ref": row.provider_ref,
        "last_error": row.last_error,
        "available_at": row.available_at.isoformat() if row.available_at else None,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
