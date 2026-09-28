from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Organization(Base):
    """A participant organization on the network (plan §5, §43).

    Type distinguishes security domains: luxeen (network operator),
    operator (e-commerce business), supplier (supply-side org).
    """

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(20), index=True)  # luxeen | operator | supplier
    country: Mapped[str] = mapped_column(String(2), default="NG")
    currency: Mapped[str] = mapped_column(String(3), default="NGN")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    """A human user belonging to an organization (plan §43).

    Auth: PBKDF2 password hash + role-based permissions. Roles:
    luxeen_admin | owner | admin | manager | agent | viewer.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)  # WhatsApp target for §39 outbound
    role: Mapped[str] = mapped_column(String(50), default="agent")
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
