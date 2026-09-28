from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Store(Base):
    """An operator storefront inside Ecos (plan §13-14).

    The storefront belongs to the operator organization; the supply
    infrastructure underneath belongs to Luxeen/Ecos.
    """

    __tablename__ = "stores"
    __table_args__ = (UniqueConstraint("slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(2), default="NG")
    currency: Mapped[str] = mapped_column(String(3), default="NGN")
    status: Mapped[str] = mapped_column(String(20), default="active")  # draft | active | suspended
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
