"""LLM provider layer for the AI Harness (plan §31+).

DeepSeek is the configured harness brain (§31): an OpenAI-compatible
chat-completions API at api.deepseek.com. When DEEPSEEK_API_KEY is not
configured, the harness degrades gracefully to a deterministic heuristic
engine so every operator still produces structured, auditable output —
clearly labelled `heuristic-fallback` in run records. Set the env var and
restart to switch the harness to live DeepSeek inference; no code changes.

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

DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
REQUEST_TIMEOUT_S = 60.0


def provider_info() -> dict[str, Any]:
    configured = bool(DEEPSEEK_API_KEY)
    return {
        "provider": "deepseek" if configured else "heuristic-fallback",
        "model": DEEPSEEK_MODEL if configured else "ecos-heuristic-v1",
        "key_configured": configured,
        "base_url": DEEPSEEK_BASE_URL if configured else None,
    }


def chat(messages: list[dict[str, str]], *, json_mode: bool = False) -> dict[str, Any]:
    if DEEPSEEK_API_KEY:
        return _chat_deepseek(messages, json_mode=json_mode)
    return _chat_fallback(messages, json_mode=json_mode)


# --------------------------------------------------------------------------
# DeepSeek (live)
# --------------------------------------------------------------------------

def _chat_deepseek(messages: list[dict[str, str]], *, json_mode: bool) -> dict[str, Any]:
    started = time.monotonic()
    body: dict[str, Any] = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.3,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    resp = httpx.post(
        f"{DEEPSEEK_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
        json=body,
        timeout=REQUEST_TIMEOUT_S,
    )
    latency_ms = int((time.monotonic() - started) * 1000)
    if resp.status_code != 200:
        raise RuntimeError(f"DeepSeek API error {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    choice = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return {
        "content": choice,
        "provider": "deepseek",
        "model": data.get("model", DEEPSEEK_MODEL),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "latency_ms": latency_ms,
    }


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
