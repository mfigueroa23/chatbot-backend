from datetime import datetime
from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class ChatThread(Base):
    """Última actividad de cada conversación de Google Chat, para borrar su memoria al caducar."""
    __tablename__ = "chat_thread"

    # El space en un mensaje directo o el hilo en un space de grupo; es el thread_id del checkpointer.
    conversation_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
