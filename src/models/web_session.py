import uuid
from datetime import datetime
from enum import StrEnum
from sqlalchemy import DateTime, Enum, Index, SmallInteger, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class WebPhase(StrEnum):
    bot = "bot"
    offering_human = "offering_human"
    collecting_contact = "collecting_contact"
    queued = "queued"
    live = "live"

class WebSession(Base):
    __tablename__ = "web_session"
    __table_args__ = (Index("ix_web_session_connected_last_seen_at", "connected", "last_seen_at"),)

    # También es el thread_id del checkpointer de LangGraph.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    phase: Mapped[WebPhase] = mapped_column(Enum(WebPhase, name="web_phase"), server_default=WebPhase.bot.value)
    contact_attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    pending_question: Mapped[str | None] = mapped_column(Text)
    connected: Mapped[bool] = mapped_column(server_default="false")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
