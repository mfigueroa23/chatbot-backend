from datetime import datetime
from sqlalchemy import DateTime, Index, SmallInteger, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class Executive(Base):
    __tablename__ = "executive"
    __table_args__ = (Index("ix_executive_username_lower", text("lower(username)"), unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80))
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text)
    failed_attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(server_default="true")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connected: Mapped[bool] = mapped_column(server_default="false")
