from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Product(Base):
    """The canonical Ecos product (plan §10).

    Supplier data is normalized into this internal representation. Operators
    interact with Ecos products, never with suppliers directly (plan §9).
    Pricing is computed by the pricing engine from supplier cost + waterfall.
    """

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int] = mapped_column(Integer, index=True)
    slug: Mapped[str | None] = mapped_column(String(280), nullable=True, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str] = mapped_column(String(4096), default="")
    category: Mapped[str] = mapped_column(String(100), default="general", index=True)
    brand: Mapped[str] = mapped_column(String(100), default="")
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    supplier_cost: Mapped[float] = mapped_column(Float)  # in `currency`
    weight_kg: Mapped[float] = mapped_column(Float, default=0.5)
    markup_pct: Mapped[float | None] = mapped_column(Float, nullable=True)  # None -> engine default
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)  # draft | active | archived
    stock: Mapped[int] = mapped_column(Integer, default=0)
    country_of_origin: Mapped[str] = mapped_column(String(2), default="CN")
    images: Mapped[list] = mapped_column(JSON, default=list)
    specs: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
