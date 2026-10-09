from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditLog(Base):
    """One auditable operation (plan §44).

    Preserves exactly what the plan requires:
      actor            -> actor_user_id / actor_label / actor_role / org_id
      action           -> `action` (semantic verb, e.g. product.price_changed)
      timestamp        -> created_at (UTC)
      object           -> entity_type + entity_id
      previous state   -> before (JSON)
      new state        -> after  (JSON)
      source           -> api | system | ai | public | automation | http
      authorization    -> actor_role + permission held (auth_context)
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    actor_user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    actor_label: Mapped[str] = mapped_column(String(255), default="")
    actor_role: Mapped[str] = mapped_column(String(30), default="", index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(60), index=True)
    entity_id: Mapped[str] = mapped_column(String(60), default="", index=True)
    before: Mapped[dict | None] = mapped_column(String(8192), nullable=True)  # JSON
    after: Mapped[dict | None] = mapped_column(String(8192), nullable=True)   # JSON
    changed: Mapped[dict | None] = mapped_column(String(4096), nullable=True) # JSON {field: {from, to}}
    source: Mapped[str] = mapped_column(String(20), default="api", index=True)
    method: Mapped[str] = mapped_column(String(10), default="")
    path: Mapped[str] = mapped_column(String(255), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    auth_context: Mapped[str] = mapped_column(String(255), default="")  # perm that authorized the call
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
