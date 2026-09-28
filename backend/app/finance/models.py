from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

ENTRY_TYPES = [
    "customer_payment",    # money in from the customer (COD collection or gateway capture)
    "supplier_payable",    # allocated out of gross: owed to the supplier
    "logistics_cost",      # allocated out of gross: owed to logistics partners
    "payment_cost",        # allocated out of gross: owed to the payment processor
    "luxeen_economics",    # allocated out of gross: Luxeen network economics (§57)
    "operator_economics",  # allocated out of gross: operator economics (§57)
    "refund",              # money out
]

PARTIES = ["customer", "supplier", "logistics", "payment_processor", "luxeen", "operator"]


class LedgerEntry(Base):
    """Immutable financial record (plan §26, §45).

    Business events (payment captured, refund issued) become financial
    events, which become ledger entries. Balances and settlements are
    derived from these entries — never from mutable application state.
    """

    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    entry_type: Mapped[str] = mapped_column(String(30), index=True)
    party: Mapped[str] = mapped_column(String(30))
    amount: Mapped[float] = mapped_column(Float)  # signed: positive = inflow to network economics
    currency: Mapped[str] = mapped_column(String(3), default="NGN")
    memo: Mapped[str] = mapped_column(String(1024), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
