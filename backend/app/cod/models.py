"""COD remittance register (plan §24 — Cash on Delivery).

The lifecycle the plan demands: COD order → expected amount → delivery
attempt → collection → *courier remittance* → *reconciliation* → settlement.

Collections already hit the ledger at the door (customer_payment inflow,
§26 waterfall). What was missing is the physical custody leg: the courier
holds network cash until they remit it. The register tracks exactly that:

    register (draft)  →  courier remits cash (remitted)  →  counted vs
    expected per line (reconciled / variance → cod_variance ledger true-up)

Every reconciled line stamps the payment's `reconciled` flag, closing the
§24 loop into §25 (payment reconciliation) and §27 (settlement inputs).
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

REGISTER_STATUSES = ["draft", "remitted", "reconciled", "cancelled"]

REGISTER_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["remitted", "cancelled"],
    "remitted": ["reconciled", "cancelled"],  # cancel after remit => dispute path
    "reconciled": [],
    "cancelled": [],
}


class CodRemittance(Base):
    """One remittance envelope between a courier and the network (§24)."""

    __tablename__ = "cod_remittances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    register_code: Mapped[str] = mapped_column(String(30), unique=True)
    org_id: Mapped[int] = mapped_column(Integer, index=True)
    carrier: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    currency: Mapped[str] = mapped_column(String(3), default="NGN")
    expected_amount: Mapped[float] = mapped_column(Float, default=0.0)  # sum of collected COD attached
    remitted_amount: Mapped[float] = mapped_column(Float, default=0.0)  # what the courier handed over
    counted_amount: Mapped[float] = mapped_column(Float, default=0.0)   # what reconciliation counted
    variance_amount: Mapped[float] = mapped_column(Float, default=0.0)  # counted - expected (negative = shortage)
    reference: Mapped[str] = mapped_column(String(120), default="")     # courier receipt / memo ref
    note: Mapped[str] = mapped_column(String(1024), default="")
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    remitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CodRemittanceLine(Base):
    """One collected COD payment inside a register, with its counted amount."""

    __tablename__ = "cod_remittance_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    remittance_id: Mapped[int] = mapped_column(Integer, index=True)
    payment_id: Mapped[int] = mapped_column(Integer, index=True)
    order_id: Mapped[int] = mapped_column(Integer, index=True)
    shipment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_amount: Mapped[float] = mapped_column(Float, default=0.0)
    counted_amount: Mapped[float] = mapped_column(Float, default=0.0)
