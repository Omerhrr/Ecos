from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Supplier(Base):
    """A supplier in the Luxeen supply network (plan §8).

    Suppliers are managed by Luxeen. Their identity and internal economics
    are never exposed to operators (plan §9 — supplier isolation).
    """

    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    country: Mapped[str] = mapped_column(String(2), default="CN")
    city: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending | verified | suspended
    rating: Mapped[float] = mapped_column(Float, default=0.0)  # 0..5 network performance rating
    lead_time_days: Mapped[int] = mapped_column(Integer, default=14)
    notes: Mapped[str] = mapped_column(String(1024), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
