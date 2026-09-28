from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LandingPage(Base):
    """A block-composed landing page (plan §15 — the landing page engine).

    Pages are owned by an operator org, composed of typed blocks (see
    blocks.py), and rendered publicly at /lp/{slug} once published.
    The special slug `home` powers the storefront home page (plan §14).
    """

    __tablename__ = "landing_pages"
    __table_args__ = (UniqueConstraint("slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(Integer, index=True)
    slug: Mapped[str] = mapped_column(String(120), index=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)  # draft | published
    blocks: Mapped[list] = mapped_column(JSON, default=list)
    theme: Mapped[dict] = mapped_column(JSON, default=dict)  # {"primary": "#0ea5e9", ...}
    seo: Mapped[dict] = mapped_column(JSON, default=dict)    # {"title","description","og_image"}
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # §15 scheduling: when set (page still draft) the scheduler flips the
    # page live automatically once this moment passes.
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_by: Mapped[int | None] = mapped_column(Integer, nullable=True)


class LandingPageVersion(Base):
    """An immutable published snapshot of a landing page (plan §15).

    Every publish (manual or scheduler-driven) freezes the exact blocks +
    theme + seo the public saw, so operators can diff history and roll back
    without rebuilding. Restore copies a snapshot back onto the draft.
    """

    __tablename__ = "landing_page_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(Integer, index=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    blocks: Mapped[list] = mapped_column(JSON, default=list)
    theme: Mapped[dict] = mapped_column(JSON, default=dict)
    seo: Mapped[dict] = mapped_column(JSON, default=dict)
    published_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    note: Mapped[str] = mapped_column(String(500), default="")

    __table_args__ = (
        UniqueConstraint("page_id", "version_no", name="uq_lp_version_page_no"),
    )
