"""Authentication primitives (plan §43 — Identity, Tenancy & Permissions).

Zero-dependency, stdlib-only implementations:
- Passwords: PBKDF2-HMAC-SHA256, 120k iterations, per-user random salt.
- Tokens: standard HS256 JWTs (header.payload.signature, base64url), 12h TTL.

Swap for passlib/PyJWT later without touching callers — the interface
(hash_password / verify_password / create_token / decode_token) is stable.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

SECRET_KEY = os.getenv("ECOS_SECRET_KEY", "ecos-dev-secret-change-in-production")
TOKEN_TTL_SECONDS = 12 * 3600
_PBKDF2_ITERATIONS = 120_000


# ---------------------------------------------------------------- passwords

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or "$" not in stored:
        return False
    try:
        _, iters, salt, digest = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(dk.hex(), digest)
    except (ValueError, TypeError):
        return False


# ------------------------------------------------------------------- tokens

def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64u_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def create_token(user_id: int, org_id: int, role: str, ttl: int = TOKEN_TTL_SECONDS) -> str:
    """Issue a signed HS256 JWT binding the user to their tenant org + role."""
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {"sub": user_id, "org_id": org_id, "role": role, "iat": now, "exp": now + ttl}
    signing_input = (
        f"{_b64u_encode(json.dumps(header, separators=(',', ':')).encode())}"
        f".{_b64u_encode(json.dumps(payload, separators=(',', ':')).encode())}"
    )
    signature = hmac.new(SECRET_KEY.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64u_encode(signature)}"


def decode_token(token: str) -> dict | None:
    """Verify signature + expiry; return the payload dict or None."""
    try:
        head, body, sig = token.split(".")
        signing_input = f"{head}.{body}"
        expected = hmac.new(SECRET_KEY.encode(), signing_input.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64u_decode(sig)):
            return None
        payload = json.loads(_b64u_decode(body))
        if int(payload.get("exp", 0)) < time.time():
            return None
        return payload
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
