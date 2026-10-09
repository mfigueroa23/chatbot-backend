import uuid
from datetime import datetime
from enum import StrEnum
from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class Channel(StrEnum):
    web = "web"
    google_chat = "google_chat"

class Conversation(Base):
    """Sesión del chat web (su id es el session_id) o conversación de Google Chat (external_key)."""
    __tablename__ = "conversation"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    channel: Mapped[Channel] = mapped_column(Enum(Channel, name="channel"))
    # Google Chat: el hilo en un space o el space en un mensaje directo; vacío en el web.
    external_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
