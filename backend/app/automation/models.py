from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

CONDITION_OPS = [
    "eq", "ne", "gt", "gte", "lt", "lte",
    "contains", "in", "not_in", "exists", "truthy",
]

ACTION_TYPES = ["notify", "escalate", "flag_product", "create_settlement_draft"]


class AutomationRule(Base):
    """A deterministic rule: WHEN <event> AND <conditions> THEN <actions> (§41).

    Rules are pure configuration — evaluation happens on every matching
    event publish, inside the same transaction, and every evaluation is
    logged to `automation_runs` for audit (§44).
    """

    __tablename__ = "automation_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(1024), default="")
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    enabled: Mapped[int] = mapped_column(Integer, default=1)  # sqlite-friendly bool
    # [{path: "to", op: "eq", value: "delivered"}, ...] — AND-combined
    conditions: Mapped[list] = mapped_column(JSON, default=list)
    # [{type: "notify", title: "...", body: "...", level: "warning", category: "automation"}]
    actions: Mapped[list] = mapped_column(JSON, default=list)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=0)
    match_count: Mapped[int] = mapped_column(Integer, default=0)
    last_matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AutomationRun(Base):
    """Audit trail: one row per (rule, event) evaluation (§44)."""

    __tablename__ = "automation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int] = mapped_column(Integer, index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    event_row_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # matched | condition_not_met | cooldown | dry_run | failed
    status: Mapped[str] = mapped_column(String(20), default="matched", index=True)
    conditions_result: Mapped[list] = mapped_column(JSON, default=list)
    actions_executed: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str] = mapped_column(String(1024), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
