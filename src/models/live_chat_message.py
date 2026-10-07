from datetime import datetime
from enum import StrEnum
from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class MessageSender(StrEnum):
    customer = "customer"
    executive = "executive"

class LiveChatMessage(Base):
    __tablename__ = "live_chat_message"
    __table_args__ = (Index("ix_live_chat_message_chat_id", "live_chat_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    live_chat_id: Mapped[int] = mapped_column(ForeignKey("live_chat.id", ondelete="CASCADE"))
    sender: Mapped[MessageSender] = mapped_column(Enum(MessageSender, name="message_sender"))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
