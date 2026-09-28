"""Landing page engine — admin API (plan §15).

All routes require authentication; reads need landing_pages:read, writes
landing_pages:write. Pages are scoped to the caller's org — platform staff
(luxeen_admin) can see and manage every org's pages.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import AuthContext, require_perm
from app.core.events import publish
from app.landing_pages import models as m
from app.landing_pages.blocks import registry_public, resolve_blocks, sanitize_blocks

router = APIRouter(prefix="/landing-pages", tags=["landing-pages"])

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class PageIn(BaseModel):
    title: str
    slug: str
    blocks: list | None = None
    theme: dict | None = None
    seo: dict | None = None
    org_id: int | None = None  # only honored for platform staff


class PagePatch(BaseModel):
    title: str | None = None
    slug: str | None = None
    blocks: list | None = None
    theme: dict | None = None
    seo: dict | None = None


def _normalize_slug(slug: str) -> str:
    s = slug.strip().lower().replace("_", "-")
    s = re.sub(r"[^a-z0-9-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def summary(p: m.LandingPage) -> dict:
    return {
        "id": p.id, "org_id": p.org_id, "slug": p.slug, "title": p.title,
        "status": p.status,
        "block_count": len(p.blocks or []),
        "updated_at": (p.updated_at or p.created_at).isoformat() if p.updated_at or p.created_at else None,
        "published_at": p.published_at.isoformat() if p.published_at else None,
        "scheduled_at": p.scheduled_at.isoformat() if p.scheduled_at else None,
    }


def detail(p: m.LandingPage) -> dict:
    return {
        **summary(p),
        "blocks": p.blocks or [],
        "theme": p.theme or {},
        "seo": p.seo or {},
    }


def _snapshot_version(db: Session, page: m.LandingPage, *, published_by: int | None = None,
                      note: str = "") -> m.LandingPageVersion:
    """Freeze the exact blocks/theme/seo being published (§15 versioning)."""
    last = (
        db.query(m.LandingPageVersion)
        .filter(m.LandingPageVersion.page_id == page.id)
        .order_by(m.LandingPageVersion.version_no.desc())
        .first()
    )
    version = m.LandingPageVersion(
        page_id=page.id,
        version_no=(last.version_no + 1) if last else 1,
        blocks=page.blocks or [], theme=page.theme or {}, seo=page.seo or {},
        published_by=published_by,
        published_at=datetime.now(timezone.utc),
        note=note or ("scheduled publish" if page.scheduled_at else ""),
    )
    db.add(version)
    db.flush()
    return version


def _scoped(ctx: AuthContext, page: m.LandingPage) -> bool:
    return ctx.is_platform or page.org_id == ctx.user.org_id


def _get_scoped(ctx: AuthContext, page_id: int, db: Session) -> m.LandingPage:
    page = db.get(m.LandingPage, page_id)
    if not page or not _scoped(ctx, page):
        raise HTTPException(404, "Landing page not found")
    return page


# ---------------------------------------------------------------- registry

@router.get("/blocks")
def block_registry(ctx: AuthContext = Depends(require_perm("landing_pages:read"))):
    """Block types + field metadata for the editor UI."""
    return registry_public()


# ------------------------------------------------------------------- CRUD

@router.get("")
def list_pages(ctx: AuthContext = Depends(require_perm("landing_pages:read")), db: Session = Depends(get_db)):
    q = db.query(m.LandingPage).order_by(m.LandingPage.id.desc())
    if not ctx.is_platform:
        q = q.filter(m.LandingPage.org_id == ctx.user.org_id)
    return [summary(p) for p in q.all()]


@router.post("", status_code=201)
def create_page(
    payload: PageIn,
    ctx: AuthContext = Depends(require_perm("landing_pages:write")),
    db: Session = Depends(get_db),
):
    slug = _normalize_slug(payload.slug)
    if not slug or not SLUG_RE.match(slug):
        raise HTTPException(400, "Slug may only contain lowercase letters, numbers and dashes")
    if db.query(m.LandingPage).filter(m.LandingPage.slug == slug).first():
        raise HTTPException(400, f"Slug '{slug}' is already taken")
    blocks, errors = sanitize_blocks(payload.blocks)
    if errors:
        raise HTTPException(400, "; ".join(errors))
    org_id = payload.org_id if (ctx.is_platform and payload.org_id) else ctx.user.org_id
    page = m.LandingPage(
        org_id=org_id, slug=slug, title=payload.title.strip(),
        blocks=blocks, theme=payload.theme or {"primary": "#00b374"},
        seo=payload.seo or {}, created_by=ctx.user.id,
    )
    db.add(page)
    db.flush()
    publish(db, "landing_page.created", {"page_id": page.id, "slug": page.slug, "org_id": org_id})
    db.commit()
    return detail(page)


@router.get("/{page_id}")
def get_page(page_id: int, ctx: AuthContext = Depends(require_perm("landing_pages:read")), db: Session = Depends(get_db)):
    return detail(_get_scoped(ctx, page_id, db))


@router.patch("/{page_id}")
def patch_page(
    page_id: int,
    payload: PagePatch,
    ctx: AuthContext = Depends(require_perm("landing_pages:write")),
    db: Session = Depends(get_db),
):
    page = _get_scoped(ctx, page_id, db)
    changes: list[str] = []
    if payload.title is not None:
        page.title = payload.title.strip()
        changes.append("title")
    if payload.slug is not None:
        slug = _normalize_slug(payload.slug)
        if not slug or not SLUG_RE.match(slug):
            raise HTTPException(400, "Invalid slug")
        clash = db.query(m.LandingPage).filter(m.LandingPage.slug == slug, m.LandingPage.id != page.id).first()
        if clash:
            raise HTTPException(400, f"Slug '{slug}' is already taken")
        page.slug = slug
        changes.append("slug")
    if payload.blocks is not None:
        blocks, errors = sanitize_blocks(payload.blocks)
        if errors:
            raise HTTPException(400, "; ".join(errors))
        page.blocks = blocks
        changes.append("blocks")
    if payload.theme is not None:
        page.theme = payload.theme
        changes.append("theme")
    if payload.seo is not None:
        page.seo = payload.seo
        changes.append("seo")
    publish(db, "landing_page.updated", {"page_id": page.id, "changes": changes})
    db.commit()
    db.refresh(page)
    return detail(page)


@router.post("/{page_id}/publish")
def publish_page(page_id: int, ctx: AuthContext = Depends(require_perm("landing_pages:write")), db: Session = Depends(get_db)):
    page = _get_scoped(ctx, page_id, db)
    page.scheduled_at = None  # a manual publish supersedes any pending schedule
    if page.status != "published":
        page.status = "published"
        page.published_at = datetime.now(timezone.utc)
    version = _snapshot_version(db, page, published_by=ctx.user.id)
    publish(db, "landing_page.published", {
        "page_id": page.id, "slug": page.slug, "version_no": version.version_no,
    })
    db.commit()
    return detail(page)


@router.post("/{page_id}/unpublish")
def unpublish_page(page_id: int, ctx: AuthContext = Depends(require_perm("landing_pages:write")), db: Session = Depends(get_db)):
    page = _get_scoped(ctx, page_id, db)
    if page.status != "draft":
        page.status = "draft"
        publish(db, "landing_page.unpublished", {"page_id": page.id, "slug": page.slug})
    db.commit()
    return detail(page)


# --------------------------------------------------------- §15 versioning

def _version_dict(v: m.LandingPageVersion) -> dict:
    return {
        "id": v.id, "page_id": v.page_id, "version_no": v.version_no,
        "block_count": len(v.blocks or []),
        "theme": v.theme or {}, "seo": v.seo or {},
        "published_by": v.published_by,
        "published_at": v.published_at.isoformat() if v.published_at else None,
        "note": v.note,
        "is_current": False,
    }


@router.get("/{page_id}/versions")
def list_versions(page_id: int, ctx: AuthContext = Depends(require_perm("landing_pages:read")), db: Session = Depends(get_db)):
    page = _get_scoped(ctx, page_id, db)
    versions = (
        db.query(m.LandingPageVersion)
        .filter(m.LandingPageVersion.page_id == page.id)
        .order_by(m.LandingPageVersion.version_no.desc())
        .all()
    )
    out = [_version_dict(v) for v in versions]
    # the live page content itself is the newest "version" until republished
    out.insert(0, {
        "id": None, "page_id": page.id, "version_no": "live",
        "block_count": len(page.blocks or []),
        "theme": page.theme or {}, "seo": page.seo or {},
        "published_by": page.created_by,
        "published_at": page.updated_at.isoformat() if page.updated_at else None,
        "note": "Current draft (not yet snapshotted)",
        "is_current": True,
    })
    return out


@router.get("/{page_id}/versions/{version_no}")
def get_version(page_id: int, version_no: int, ctx: AuthContext = Depends(require_perm("landing_pages:read")), db: Session = Depends(get_db)):
    _get_scoped(ctx, page_id, db)
    v = (
        db.query(m.LandingPageVersion)
        .filter(m.LandingPageVersion.page_id == page_id,
                m.LandingPageVersion.version_no == version_no)
        .first()
    )
    if not v:
        raise HTTPException(404, "Version not found")
    return {**_version_dict(v), "blocks": v.blocks or []}


class RestoreIn(BaseModel):
    publish: bool = False  # restore straight back to the live page?


@router.post("/{page_id}/versions/{version_no}/restore")
def restore_version(
    page_id: int, version_no: int, payload: RestoreIn,
    ctx: AuthContext = Depends(require_perm("landing_pages:write")),
    db: Session = Depends(get_db),
):
    """Roll back: copy a snapshot's blocks/theme/seo onto the page.

    - page is a draft  -> restored content lands as a draft for review
    - page is published -> the rollback goes live immediately (a live page
      must never silently diverge from what history says it published) and
      the rollback itself is snapshotted as a new version.
    `publish: true` additionally (re)publishes a draft page in one step.
    """
    page = _get_scoped(ctx, page_id, db)
    v = (
        db.query(m.LandingPageVersion)
        .filter(m.LandingPageVersion.page_id == page_id,
                m.LandingPageVersion.version_no == version_no)
        .first()
    )
    if not v:
        raise HTTPException(404, "Version not found")
    page.blocks = v.blocks or []
    page.theme = v.theme or {}
    page.seo = v.seo or {}
    page.scheduled_at = None
    if payload.publish:
        if page.status != "published":
            page.status = "published"
            page.published_at = datetime.now(timezone.utc)
        version = _snapshot_version(
            db, page, published_by=ctx.user.id,
            note=f"restore of v{version_no}",
        )
        publish(db, "landing_page.published", {
            "page_id": page.id, "slug": page.slug, "version_no": version.version_no,
            "restored_from": version_no,
        })
    else:
        if page.status == "published":
            # live content changed under the published flag -> snapshot the rollback too
            version = _snapshot_version(
                db, page, published_by=ctx.user.id,
                note=f"restore of v{version_no}",
            )
            publish(db, "landing_page.updated", {
                "page_id": page.id, "slug": page.slug,
                "restored_from": version_no, "version_no": version.version_no,
            })
        else:
            publish(db, "landing_page.updated", {
                "page_id": page.id, "slug": page.slug, "restored_from": version_no,
            })
    db.commit()
    db.refresh(page)
    return detail(page)


# --------------------------------------------------------- §15 scheduling

class ScheduleIn(BaseModel):
    publish_at: datetime


@router.post("/{page_id}/schedule")
def schedule_page(
    page_id: int, payload: ScheduleIn,
    ctx: AuthContext = Depends(require_perm("landing_pages:write")),
    db: Session = Depends(get_db),
):
    """Queue this page to go live automatically at `publish_at` (§15)."""
    page = _get_scoped(ctx, page_id, db)
    when = payload.publish_at
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    if when <= datetime.now(timezone.utc):
        raise HTTPException(400, "publish_at must be in the future — use Publish for immediate go-live")
    page.scheduled_at = when
    page.scheduled_by = ctx.user.id
    publish(db, "landing_page.scheduled", {
        "page_id": page.id, "slug": page.slug,
        "publish_at": when.isoformat(),
    })
    db.commit()
    return detail(page)


@router.delete("/{page_id}/schedule")
def cancel_schedule(page_id: int, ctx: AuthContext = Depends(require_perm("landing_pages:write")), db: Session = Depends(get_db)):
    page = _get_scoped(ctx, page_id, db)
    page.scheduled_at = None
    db.commit()
    return detail(page)


def run_due_schedules(db: Session) -> list[int]:
    """Scheduler tick (called from the app lifespan loop): flip every due
    scheduled page live, snapshotting each as a new version. Returns ids."""
    now = datetime.now(timezone.utc)
    due = (
        db.query(m.LandingPage)
        .filter(m.LandingPage.scheduled_at.isnot(None),
                m.LandingPage.scheduled_at <= now)
        .all()
    )
    flipped: list[int] = []
    for page in due:
        page.status = "published"
        page.published_at = now
        page.scheduled_at = None
        version = _snapshot_version(db, page, note="scheduled publish")
        publish(db, "landing_page.published", {
            "page_id": page.id, "slug": page.slug,
            "version_no": version.version_no, "scheduled": True,
        })
        flipped.append(page.id)
    if flipped:
        db.commit()
    return flipped


@router.delete("/{page_id}", status_code=204)
def delete_page(page_id: int, ctx: AuthContext = Depends(require_perm("landing_pages:write")), db: Session = Depends(get_db)):
    page = _get_scoped(ctx, page_id, db)
    publish(db, "landing_page.deleted", {"page_id": page.id, "slug": page.slug})
    db.delete(page)
    db.commit()
