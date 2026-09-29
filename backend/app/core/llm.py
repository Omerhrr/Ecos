"""LLM provider layer for the AI Harness (plan §31+).

DeepSeek is the configured harness brain (§31): an OpenAI-compatible
chat-completions API at api.deepseek.com. When no key is configured, the
harness degrades gracefully to a deterministic heuristic engine so every
operator still produces structured, auditable output — clearly labelled
`heuristic-fallback` in run records.

Key flow (§31 completion) — resolution chain, evaluated at every call so a
saved key flips the harness live with NO restart:

    1. ai_provider_settings row (admin UI, obfuscated at rest by secretbox)
    2. DEEPSEEK_API_KEY env var (.env — headless deployments)
    3. none -> deterministic heuristic fallback

Contract used by operators:
    chat(messages, *, json_mode=False) -> {
        "content": str, "provider": str, "model": str,
        "prompt_tokens": int, "completion_tokens": int, "latency_ms": int,
    }
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import text

from app.core import secretbox

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
REQUEST_TIMEOUT_S = 60.0
MAX_ATTEMPTS = 2  # one retry on transient transport failures


# --------------------------------------------------------------------------
# Settings store (ai_provider_settings, singleton id=1) — read at call time
# --------------------------------------------------------------------------

def _read_settings_row() -> dict[str, Any] | None:
    """Singleton provider row via raw SQL — no model import cycle, and it
    degrades to None when the table does not exist yet (fresh DB mid-migrate)."""
    from app.core.database import SessionLocal  # local: avoid import-time cycles

    try:
        db = SessionLocal()
        try:
            row = db.execute(
                text(
                    "SELECT provider, api_key_enc, model, base_url, "
                    "last_test_at, last_test_ok, last_test_latency_ms, last_test_error "
                    "FROM ai_provider_settings WHERE id = 1"
                )
            ).mappings().first()
            return dict(row) if row else None
        finally:
            db.close()
    except Exception:  # noqa: BLE001 — table missing / DB not ready -> env-only mode
        return None


def _settings() -> dict[str, Any]:
    """Effective provider configuration (decrypted), DB row wins over env."""
    row = _read_settings_row() or {}
    db_key = secretbox.decrypt(row.get("api_key_enc") or "")
    db_model = (row.get("model") or "").strip()
    db_base = (row.get("base_url") or "").strip()
    env_key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    if db_key:
        source, api_key = "database", db_key
    elif env_key:
        source, api_key = "env", env_key
    else:
        source, api_key = None, ""
    return {
        "key_source": source,
        "api_key": api_key,
        "key_hint": secretbox.key_hint(api_key) if api_key else None,
        "model": db_model or os.getenv("DEEPSEEK_MODEL") or DEFAULT_MODEL,
        "base_url": (db_base or os.getenv("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
        "last_test_at": row.get("last_test_at"),
        "last_test_ok": bool(row["last_test_ok"]) if row.get("last_test_ok") is not None else None,
        "last_test_latency_ms": row.get("last_test_latency_ms"),
        "last_test_error": row.get("last_test_error") or "",
    }


def write_settings(
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    updated_by: int | None = None,
) -> None:
    """Upsert the singleton provider row (ai key flow). api_key=None keeps
    the stored key; "" clears it; a value replaces it (encrypted)."""
    from app.ai_harness import models as ai_m  # local: cycle-safe
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        row = db.get(ai_m.AiProviderSetting, 1)
        if row is None:
            row = ai_m.AiProviderSetting(id=1)
            db.add(row)
        if api_key is not None:
            row.api_key_enc = secretbox.encrypt(api_key)
        if model is not None:
            row.model = model.strip()[:60]
        if base_url is not None:
            row.base_url = base_url.strip()[:255]
        row.updated_by = updated_by
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()


def record_test_result(*, ok: bool, latency_ms: int | None, error: str = "") -> None:
    """Persist the outcome of POST /ai/provider/test onto the settings row."""
    from app.ai_harness import models as ai_m  # cycle-safe local import
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        row = db.get(ai_m.AiProviderSetting, 1)
        if row is None:
            row = ai_m.AiProviderSetting(id=1)
            db.add(row)
        row.last_test_at = datetime.now(timezone.utc)
        row.last_test_ok = 1 if ok else 0
        row.last_test_latency_ms = latency_ms
        row.last_test_error = (error or "")[:500]
        db.commit()
    finally:
        db.close()


def _api_key() -> str:
    return _settings()["api_key"]


def _base_url() -> str:
    return _settings()["base_url"]


def _model() -> str:
    return _settings()["model"]


def provider_info() -> dict[str, Any]:
    s = _settings()
    configured = bool(s["api_key"])
    last_test_at = s["last_test_at"]
    if configured and last_test_at is not None:
        # raw SQL on SQLite returns datetime columns as strings
        if isinstance(last_test_at, str):
            last_test_iso = last_test_at
        else:
            last_test_iso = last_test_at.isoformat()
    else:
        last_test_iso = None
    return {
        "provider": "deepseek" if configured else "heuristic-fallback",
        "model": s["model"] if configured else "ecos-heuristic-v1",
        "key_configured": configured,
        "key_source": s["key_source"],
        "key_hint": s["key_hint"],
        "base_url": s["base_url"] if configured else None,
        "last_test_ok": s["last_test_ok"] if configured else None,
        "last_test_at": last_test_iso,
        "last_test_latency_ms": s["last_test_latency_ms"] if configured else None,
        "last_test_error": s["last_test_error"] if configured and not s["last_test_ok"] else "",
        "live_instructions": (
            "Paste your DeepSeek API key in AI Harness → Provider (stored encrypted "
            "in your own database) or set DEEPSEEK_API_KEY in the project-root .env — "
            "the harness flips to live inference instantly, no restart needed."
        ) if not configured else None,
    }
    return info


def chat(messages: list[dict[str, str]], *, json_mode: bool = False) -> dict[str, Any]:
    if _api_key():
        return _chat_deepseek(messages, json_mode=json_mode)
    return _chat_fallback(messages, json_mode=json_mode)


def test_connection() -> dict[str, Any]:
    """Tiny live ping used by POST /ai/provider/test. Raises on failure."""
    if not _api_key():
        raise RuntimeError(
            "No DeepSeek key configured — the harness is running on the deterministic "
            "heuristic fallback. Paste a key in AI Harness → Provider, or set "
            "DEEPSEEK_API_KEY in the project-root .env."
        )
    started = time.monotonic()
    result = _chat_deepseek(
        [{"role": "user", "content": "Reply with the single word: pong"}],
        json_mode=False,
    )
    return {
        "ok": True,
        "provider": "deepseek",
        "model": result["model"],
        "latency_ms": result["latency_ms"],
        "reply": result["content"][:80],
        "total_ms": int((time.monotonic() - started) * 1000),
    }


# --------------------------------------------------------------------------
# DeepSeek (live)
# --------------------------------------------------------------------------

def _chat_deepseek(messages: list[dict[str, str]], *, json_mode: bool) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": _model(),
        "messages": messages,
        "temperature": 0.3,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        started = time.monotonic()
        try:
            resp = httpx.post(
                f"{_base_url()}/chat/completions",
                headers={"Authorization": f"Bearer {_api_key()}"},
                json=body,
                timeout=REQUEST_TIMEOUT_S,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
            if attempt < MAX_ATTEMPTS:
                time.sleep(1.0 * attempt)
                continue
            raise RuntimeError(f"DeepSeek unreachable after {attempt} attempt(s): {exc}") from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        if resp.status_code == 200:
            data = resp.json()
            choice = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            return {
                "content": choice,
                "provider": "deepseek",
                "model": data.get("model", _model()),
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "latency_ms": latency_ms,
            }
        # 4xx are permanent — retrying won't help; 5xx may be transient
        if resp.status_code < 500 or attempt == MAX_ATTEMPTS:
            raise RuntimeError(f"DeepSeek API error {resp.status_code}: {resp.text[:300]}")
        last_error = RuntimeError(f"DeepSeek {resp.status_code}")
        time.sleep(1.0 * attempt)

    raise RuntimeError(f"DeepSeek call failed: {last_error}")


# --------------------------------------------------------------------------
# Deterministic fallback (no API key) — structured, auditable, offline
# --------------------------------------------------------------------------

def _extract_json_block(text: str) -> str | None:
    match = re.search(r"\{[\s\S]*\}", text)
    return match.group(0) if match else None


def _chat_fallback(messages: list[dict[str, str]], *, json_mode: bool) -> dict[str, Any]:
    """The heuristic engine inspects the operator's instruction block, which
    services embed as a `[[HEURISTIC]] {...}` hint inside the system prompt,
    and returns that payload as the structured response. Operators compute
    their payloads from real database state, so the fallback output is
    genuinely derived from live data — only the prose is canned."""
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    match = re.search(r"\[\[HEURISTIC\]\]\s*(\{[\s\S]*\})", system)
    payload = match.group(1) if match else json.dumps({"note": "no heuristic hint provided"})
    started = time.monotonic()
    content = json.dumps(json.loads(payload), indent=2, ensure_ascii=False)
    return {
        "content": content,
        "provider": "heuristic-fallback",
        "model": "ecos-heuristic-v1",
        "prompt_tokens": sum(len(m["content"]) for m in messages) // 4,
        "completion_tokens": len(content) // 4,
        "latency_ms": max(1, int((time.monotonic() - started) * 1000)),
    }
