from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

CAMPAIGN_CHANNELS = [
    "meta_ads", "google_ads", "tiktok", "whatsapp", "referral", "organic", "email", "other",
]

CAMPAIGN_STATUSES = ["draft", "active", "paused", "ended"]


class Campaign(Base):
    """A paid/organic acquisition campaign (plan §16).

    A campaign owns a `utm_campaign` key: any lead whose raw UTM payload or
    free-text campaign field matches it is attributed to this campaign.
    Landing pages can carry the UTM too — a visitor arriving on
    /lp/{slug}?utm_campaign=... propagates the tag into their order intent.
    """

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(255))
    channel: Mapped[str] = mapped_column(String(30), default="other")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    utm_campaign: Mapped[str] = mapped_column(String(255), index=True)  # attribution key
    landing_page_slug: Mapped[str] = mapped_column(String(255), default="")
    budget_ngn: Mapped[float] = mapped_column(Float, default=0.0)  # spend, for CPA
    notes: Mapped[str] = mapped_column(String(1024), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
