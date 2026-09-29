"""Dev-grade at-rest obfuscation for the stored DeepSeek key (plan §31 key flow).

Pure stdlib: an HMAC-SHA256 keystream XOR ("secretbox"). The key material
never appears in plaintext in the database; a per-installation random seed
lives in db/.kseed (created on first use, gitignored).

Honest scope: this is obfuscation-at-rest for a self-hosted dev/appliance
database — anyone with filesystem access to BOTH the DB and the seed file
can recover the key. It is not a secrets vault; it prevents casual
shoulder-surfing of DB dumps and keeps the key out of backups and logs.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from pathlib import Path

_SEED_PATH = Path(__file__).resolve().parents[3] / "db" / ".kseed"
_LABEL = b"ecos-ai-provider-key-v1"


def _seed() -> bytes:
    """Per-installation random seed, created once (0600)."""
    _SEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not _SEED_PATH.exists():
        _SEED_PATH.write_bytes(os.urandom(32))
        try:
            os.chmod(_SEED_PATH, 0o600)
        except OSError:
            pass
    return _SEED_PATH.read_bytes()


def _keystream(nbytes: int) -> bytes:
    """HMAC-DRBG style stream: blocks of sha256(seed || label || counter)."""
    seed = _seed()
    out = bytearray()
    counter = 0
    while len(out) < nbytes:
        out.extend(hmac.new(seed, _LABEL + counter.to_bytes(4, "big"), hashlib.sha256).digest())
        counter += 1
    return bytes(out[:nbytes])


def encrypt(plaintext: str) -> str:
    """plaintext -> base64(blob). Empty input returns '' (key not set)."""
    raw = (plaintext or "").strip().encode("utf-8")
    if not raw:
        return ""
    ks = _keystream(len(raw) + 32)
    mac = ks[:32]
    body = bytes(b ^ k for b, k in zip(raw, ks[32:]))
    return base64.urlsafe_b64encode(mac + body).decode("ascii")


def decrypt(blob: str) -> str:
    """base64(blob) -> plaintext. '' / malformed input returns ''."""
    if not blob:
        return ""
    try:
        data = base64.urlsafe_b64decode(blob.encode("ascii"))
    except Exception:  # noqa: BLE001 — corrupt blob means "not set"
        return ""
    if len(data) <= 32:
        return ""
    ks = _keystream(len(data))
    mac, body = data[:32], data[32:]
    raw = bytes(b ^ k for b, k in zip(body, ks[32:]))
    # constant-time equality on the stored MAC
    if not hmac.compare_digest(mac, ks[:32]):
        return ""
    return raw.decode("utf-8", errors="replace")


def key_hint(plaintext: str) -> str:
    """Human-safe hint, e.g. 'sk-…4f2a' — never enough to reconstruct."""
    tail = plaintext[-4:] if len(plaintext) >= 8 else "****"
    prefix = plaintext[:3] if plaintext.startswith("sk-") else ""
    return f"{prefix}…{tail}" if prefix else f"…{tail}"
