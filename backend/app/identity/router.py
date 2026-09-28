from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import AuthContext, require_auth, require_perm
from app.core.events import publish
from app.core.permissions import ROLE_PERMISSIONS
from app.core.security import create_token, hash_password, verify_password
from app.identity import models as m

router = APIRouter(tags=["identity"])
auth_router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


class UserIn(BaseModel):
    name: str
    email: str
    password: str
    phone: str | None = None
    role: str = "agent"
    org_id: int | None = None  # only honored for platform staff


def user_dict(u: m.User) -> dict:
    return {
        "id": u.id, "org_id": u.org_id, "name": u.name,
        "email": u.email, "phone": u.phone, "role": u.role, "is_active": u.is_active,
    }


def org_dict(o: m.Organization | None) -> dict | None:
    if not o:
        return None
    return {"id": o.id, "name": o.name, "type": o.type, "country": o.country, "currency": o.currency}


@router.get("/orgs")
def list_orgs(ctx: AuthContext = Depends(require_auth), db: Session = Depends(get_db)):
    q = db.query(m.Organization)
    if not ctx.is_platform:
        q = q.filter(m.Organization.id == ctx.user.org_id)  # tenant isolation
    return [org_dict(o) for o in q.all()]


@router.get("/users")
def list_users(ctx: AuthContext = Depends(require_auth), db: Session = Depends(get_db)):
    q = db.query(m.User)
    if not ctx.is_platform:
        q = q.filter(m.User.org_id == ctx.user.org_id)
    return [user_dict(u) for u in q.order_by(m.User.id).all()]


@router.post("/users", status_code=201)
def create_user(
    payload: UserIn,
    ctx: AuthContext = Depends(require_perm("identity:manage")),
    db: Session = Depends(get_db),
):
    """Provision a user inside the caller's org (platform staff may target any org)."""
    if payload.role not in ROLE_PERMISSIONS:
        raise HTTPException(400, f"Unknown role: {payload.role}. Valid: {sorted(ROLE_PERMISSIONS)}")
    email = payload.email.strip().lower()
    if db.query(m.User).filter(m.User.email == email).first():
        raise HTTPException(400, "Email already registered")
    org_id = payload.org_id if (ctx.is_platform and payload.org_id) else ctx.user.org_id
    user = m.User(
        org_id=org_id, name=payload.name.strip(), email=email,
        phone=(payload.phone or None),
        role=payload.role, password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.flush()
    publish(db, "user.created", {"user_id": user.id, "org_id": org_id, "role": user.role})
    db.commit()
    return user_dict(user)


# ------------------------------------------------------------------ /auth

@auth_router.post("/login")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.query(m.User).filter(m.User.email == payload.email.strip().lower()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(403, "This account is disabled")
    org = db.get(m.Organization, user.org_id)
    return {
        "token": create_token(user.id, user.org_id, user.role),
        "user": user_dict(user),
        "org": org_dict(org),
        "permissions": ROLE_PERMISSIONS.get(user.role, []),
    }


@auth_router.get("/me")
def me(ctx: AuthContext = Depends(require_auth)):
    return {
        "user": user_dict(ctx.user),
        "org": org_dict(ctx.org),
        "permissions": ctx.permissions,
    }


@auth_router.post("/refresh")
def refresh(ctx: AuthContext = Depends(require_auth), db: Session = Depends(get_db)):
    """Rotate a still-valid token for a fresh 12h lease (§43 session continuity).

    The current token is validated by require_auth exactly like any other
    call — so a stolen/expired token gains nothing — and the user's status
    and role are re-checked against the DB, so deactivations and role
    changes take effect at refresh time, not just at login.
    """
    if not ctx.user.is_active:
        raise HTTPException(403, "This account is disabled")
    return {
        "token": create_token(ctx.user.id, ctx.user.org_id, ctx.user.role),
        "user": user_dict(ctx.user),
        "org": org_dict(ctx.org),
        "permissions": ROLE_PERMISSIONS.get(ctx.user.role, []),
    }
