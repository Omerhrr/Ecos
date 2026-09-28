"""FastAPI auth dependencies (plan §43).

- get_auth_context : resolves Bearer token -> AuthContext (or None)
- require_auth     : 401 unless authenticated
- require_perm(p)  : dependency factory — 403 unless the caller holds `p`

Every router that touches tenant data depends on these; the AuthContext
carries user, org, role and the resolved permission set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import permissions_for_role
from app.core.security import decode_token
from app.identity import models as im


@dataclass
class AuthContext:
    user: im.User
    org: im.Organization | None
    role: str
    permissions: list[str]

    @property
    def is_platform(self) -> bool:
        return self.role == "luxeen_admin"

    def can(self, perm: str) -> bool:
        return perm in self.permissions


def _extract_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


def get_auth_context(
    request: Request, db: Session = Depends(get_db)
) -> AuthContext | None:
    token = _extract_token(request)
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    user = db.get(im.User, int(payload.get("sub", 0)))
    if not user or not user.is_active:
        return None
    org = db.get(im.Organization, user.org_id)
    return AuthContext(
        user=user, org=org, role=user.role, permissions=permissions_for_role(user.role)
    )


def require_auth(ctx: AuthContext | None = Depends(get_auth_context)) -> AuthContext:
    if ctx is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return ctx


def require_perm(perm: str) -> Callable[..., AuthContext]:
    def dep(ctx: AuthContext = Depends(require_auth)) -> AuthContext:
        if not ctx.can(perm):
            raise HTTPException(status_code=403, detail=f"Missing permission: {perm}")
        return ctx

    return dep
