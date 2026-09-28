"""Marketing campaigns + attribution API (plan §16)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_perm
from app.core.events import publish
from app.marketing import models as m
from app.marketing import service

router = APIRouter(
    prefix="/marketing", tags=["marketing"],
    dependencies=[Depends(require_perm("marketing:read"))],
)


class CampaignIn(BaseModel):
    name: str
    channel: str = "other"
    status: str = "active"
    utm_campaign: str
    landing_page_slug: str = ""
    budget_ngn: float = 0.0
    notes: str = ""


class CampaignPatch(BaseModel):
    name: str | None = None
    channel: str | None = None
    status: str | None = None
    landing_page_slug: str | None = None
    budget_ngn: float | None = None
    notes: str | None = None


def serialize(c: m.Campaign) -> dict:
    return {
        "id": c.id, "org_id": c.org_id, "name": c.name, "channel": c.channel,
        "status": c.status, "utm_campaign": c.utm_campaign,
        "landing_page_slug": c.landing_page_slug, "budget_ngn": c.budget_ngn,
        "notes": c.notes, "created_at": c.created_at.isoformat(),
    }


@router.get("/campaigns")
def list_campaigns(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(m.Campaign).order_by(m.Campaign.id.desc())
    if status:
        q = q.filter(m.Campaign.status == status)
    return [serialize(c) for c in q.all()]


@router.post("/campaigns", status_code=201, dependencies=[Depends(require_perm("marketing:write"))])
def create_campaign(payload: CampaignIn, db: Session = Depends(get_db)):
    if payload.channel not in m.CAMPAIGN_CHANNELS:
        raise HTTPException(400, f"Invalid channel: {payload.channel}")
    if payload.status not in m.CAMPAIGN_STATUSES:
        raise HTTPException(400, f"Invalid status: {payload.status}")
    key = payload.utm_campaign.strip().lower()
    if not key:
        raise HTTPException(400, "utm_campaign key is required")
    dup = db.query(m.Campaign).filter(m.Campaign.utm_campaign == key).first()
    if dup:
        raise HTTPException(400, f"Campaign with utm key '{key}' already exists (#{dup.id})")

    c = m.Campaign(
        name=payload.name.strip() or key, channel=payload.channel, status=payload.status,
        utm_campaign=key, landing_page_slug=payload.landing_page_slug.strip(),
        budget_ngn=payload.budget_ngn, notes=payload.notes,
    )
    db.add(c)
    db.flush()
    publish(db, "campaign.created", {
        "campaign_id": c.id, "name": c.name, "channel": c.channel, "utm_campaign": c.utm_campaign,
    })
    db.commit()
    return serialize(c)


@router.patch("/campaigns/{campaign_id}", dependencies=[Depends(require_perm("marketing:write"))])
def patch_campaign(campaign_id: int, payload: CampaignPatch, db: Session = Depends(get_db)):
    c = db.get(m.Campaign, campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")
    changes = payload.model_dump(exclude_none=True)
    if "status" in changes and changes["status"] not in m.CAMPAIGN_STATUSES:
        raise HTTPException(400, f"Invalid status: {changes['status']}")
    if "channel" in changes and changes["channel"] not in m.CAMPAIGN_CHANNELS:
        raise HTTPException(400, f"Invalid channel: {changes['channel']}")
    for k, v in changes.items():
        setattr(c, k, v)
    publish(db, "campaign.updated", {"campaign_id": c.id, "changes": list(changes.keys())})
    db.commit()
    return serialize(c)


@router.get("/attribution")
def attribution(db: Session = Depends(get_db)):
    """Where do our leads, orders and naira come from? (§16)."""
    return service.campaign_report(db)
