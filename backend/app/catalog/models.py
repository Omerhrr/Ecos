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
    videos: Mapped[list] = mapped_column(JSON, default=list)  # §10: video media (URLs/objects)
    specs: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


class ProductVariant(Base):
    """A sellable variant of a product (plan §10 — catalog depth).

    A product keeps its canonical identity; variants are the buyable faces
    of it (size / color / bundle...). Each variant carries its own SKU code,
    a supplier-cost delta (repriced through the same §12 waterfall — margin
    logic stays derived from supplier truth, never hand-set), a weight delta
    for logistics economics, and its own network-level stock guard.

    Warehouse stock remains pooled at product level (§22); the variant
    counter is the storefront oversell guard for that specific option.
    """

    __tablename__ = "product_variants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(Integer, index=True)
    sku: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    option_name: Mapped[str] = mapped_column(String(60), default="")   # e.g. "Color"
    option_value: Mapped[str] = mapped_column(String(120), default="") # e.g. "Midnight Black"
    cost_delta: Mapped[float] = mapped_column(Float, default=0.0)      # in product.currency
    weight_delta_kg: Mapped[float] = mapped_column(Float, default=0.0)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    image: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)  # active | archived
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
