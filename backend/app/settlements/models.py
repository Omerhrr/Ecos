from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

SETTLEMENT_STATUSES = ["draft", "approved", "executed", "cancelled"]

SETTLEMENT_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["approved", "cancelled"],
    "approved": ["executed", "cancelled"],
    "executed": [],
    "cancelled": [],
}


class SettlementRun(Base):
    """A settlement batch (plan §27).

    Ecos derives obligations from the immutable ledger (§26): every paid
    order writes signed entries — payables to the supplier, logistics
    partners, the payment processor, Luxeen network economics, the
    operator, and customer refunds. A SettlementRun groups currently
    unsettled payables into an explicit, approvable batch and, on
    execution, marks the underlying ledger entries as settled.

    Lifecycle:  draft -> approved -> executed   (cancel exits from draft/approved)
    """

    __tablename__ = "settlement_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_number: Mapped[str] = mapped_column(String(30), unique=True)
    org_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    currency: Mapped[str] = mapped_column(String(3), default="NGN")
    total_amount: Mapped[float] = mapped_column(Float, default=0.0)  # signed sum of lines
    entry_count: Mapped[int] = mapped_column(Integer, default=0)
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(String(1024), default="")
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SettlementLine(Base):
    """One counterparty bucket inside a settlement run.

    `counterparty` resolves the generic ledger party into a concrete
    entity (e.g. the supplier that fulfilled the orders). `entry_ids`
    records exactly which immutable ledger entries this line settles,
    so finance can always trace a payout back to orders.
    """

    __tablename__ = "settlement_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    entry_type: Mapped[str] = mapped_column(String(30))
    party: Mapped[str] = mapped_column(String(30))
    counterparty: Mapped[str] = mapped_column(String(255), default="")
    currency: Mapped[str] = mapped_column(String(3), default="NGN")
    amount: Mapped[float] = mapped_column(Float, default=0.0)  # signed, negative = payout
    entry_count: Mapped[int] = mapped_column(Integer, default=0)
    entry_ids: Mapped[list] = mapped_column(JSON, default=list)
