"""LLM provider layer for the AI Harness (plan §31+).

DeepSeek is the configured harness brain (§31): an OpenAI-compatible
chat-completions API at api.deepseek.com. When DEEPSEEK_API_KEY is not
configured, the harness degrades gracefully to a deterministic heuristic
engine so every operator still produces structured, auditable output —
clearly labelled `heuristic-fallback` in run records. Set the env var
(backend reads the project-root .env) and restart to switch the harness
to live DeepSeek inference; no code changes.

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
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
REQUEST_TIMEOUT_S = 60.0
MAX_ATTEMPTS = 2  # one retry on transient transport failures


def _api_key() -> str:
    """Read at call time so a .env edit + restart (or live reload) is honoured."""
    return (os.getenv("DEEPSEEK_API_KEY") or "").strip()


def _base_url() -> str:
    return (os.getenv("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def _model() -> str:
    return os.getenv("DEEPSEEK_MODEL") or DEFAULT_MODEL


def provider_info() -> dict[str, Any]:
    configured = bool(_api_key())
    return {
        "provider": "deepseek" if configured else "heuristic-fallback",
        "model": _model() if configured else "ecos-heuristic-v1",
        "key_configured": configured,
        "base_url": _base_url() if configured else None,
        "live_instructions": (
            "Add DEEPSEEK_API_KEY=<key> to the project-root .env and restart the API — "
            "every operator flips to live inference with zero code changes."
        ) if not configured else None,
    }


def chat(messages: list[dict[str, str]], *, json_mode: bool = False) -> dict[str, Any]:
    if _api_key():
        return _chat_deepseek(messages, json_mode=json_mode)
    return _chat_fallback(messages, json_mode=json_mode)


def test_connection() -> dict[str, Any]:
    """Tiny live ping used by POST /ai/provider/test. Raises on failure."""
    if not _api_key():
        raise RuntimeError(
            "DEEPSEEK_API_KEY is not configured — the harness is running on the "
            "deterministic heuristic fallback. Add the key to the project-root .env "
            "and restart the API."
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
