from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

OPERATOR_STATUSES = ["active", "paused"]
AUTONOMY_MODES = ["suggest", "act_with_approval"]  # §37 governance ladder (phase 1)


class AiOperator(Base):
    """A deployed AI operator (plan §31-33).

    Operators are narrow, tool-scoped roles built from a registry blueprint:
    each one reads live Ecos state through its service function and returns
    a structured proposal. The harness records every run — inputs, outputs,
    token cost, latency — and governance (§37-38) gates anything that
    mutates business state behind human approval.
    """

    __tablename__ = "ai_operators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    code: Mapped[str] = mapped_column(String(50), index=True)  # registry blueprint code
    name: Mapped[str] = mapped_column(String(120))
    role_description: Mapped[str] = mapped_column(String(512), default="")
    system_prompt: Mapped[str] = mapped_column(String(4096), default="")
    autonomy: Mapped[str] = mapped_column(String(30), default="act_with_approval")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    model: Mapped[str] = mapped_column(String(60), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiRun(Base):
    """One execution of an operator — the harness audit record (§31, §38).

    `status` tracks execution (succeeded/failed); `proposal_status` tracks
    governance (pending/approved/rejected/applied, NULL for advisory-only
    operators like the demand forecaster whose output mutates nothing).
    """

    __tablename__ = "ai_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    operator_id: Mapped[int] = mapped_column(Integer, index=True)
    org_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="succeeded", index=True)
    proposal_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String(2048), default="")
    provider: Mapped[str] = mapped_column(String(40), default="")
    model: Mapped[str] = mapped_column(String(60), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    approved_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
