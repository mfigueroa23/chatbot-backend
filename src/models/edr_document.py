import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class EdrDocumentRecord(Base):
    """EDR guardado como Google Doc; el más reciente de una conversación es el que se sigue editando (spec 003, RF-12).
    Se borra con su conversación; el documento queda en Drive."""
    __tablename__ = "edr_document"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversation.id", ondelete="CASCADE"), index=True)
    drive_file_id: Mapped[str] = mapped_column(String(255))
    web_link: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    # El último EDR guardado, para editarlo sin volver a leer el documento de Drive.
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
