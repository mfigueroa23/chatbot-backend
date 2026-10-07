import uuid
from datetime import datetime
from enum import StrEnum
from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class LiveChatStatus(StrEnum):
    waiting = "waiting"
    assigned = "assigned"
    closed = "closed"

class CloseReason(StrEnum):
    executive = "executive"
    customer_left = "customer_left"
    executive_timeout = "executive_timeout"
    schedule_end = "schedule_end"

class LiveChat(Base):
    __tablename__ = "live_chat"
    __table_args__ = (
        # Una sesión web tiene como mucho un chat abierto.
        Index(
            "ux_live_chat_open_web_session",
            "web_session_id",
            unique=True,
            postgresql_where=text("status <> 'closed'"),
        ),
        Index("ix_live_chat_status_created_at", "status", "created_at"),
        Index("ix_live_chat_assigned_executive", "executive_id", postgresql_where=text("status = 'assigned'")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    web_session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("web_session.id", ondelete="CASCADE"))
    status: Mapped[LiveChatStatus] = mapped_column(Enum(LiveChatStatus, name="live_chat_status"))
    customer_name: Mapped[str] = mapped_column(String(120))
    customer_contact: Mapped[str] = mapped_column(String(320))
    pending_question: Mapped[str] = mapped_column(Text)
    executive_id: Mapped[int | None] = mapped_column(ForeignKey("executive.id"))
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executive_disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_reason: Mapped[CloseReason | None] = mapped_column(Enum(CloseReason, name="close_reason"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
