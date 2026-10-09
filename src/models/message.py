import uuid
from datetime import datetime
from enum import StrEnum
from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class MessageRole(StrEnum):
    user = "user"
    assistant = "assistant"

class Message(Base):
    """Solo el mensaje del usuario y la respuesta final: las subtareas de los sub-agentes no se guardan."""
    __tablename__ = "message"
    __table_args__ = (Index("ix_message_conversation_id_id", "conversation_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversation.id", ondelete="CASCADE"))
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole, name="message_role"))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
