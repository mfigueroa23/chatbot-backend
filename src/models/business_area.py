from enum import StrEnum
from sqlalchemy import Enum, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class AreaScope(StrEnum):
    internal = "internal"
    external = "external"

class BusinessArea(Base):
    """Cada área activa es un sub-agente: agregar o desactivar un área no requiere código (RF-4)."""
    __tablename__ = "business_area"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(Text)
    # internal: solo la ve el agente interno (Google Chat); external: solo el externo (chat web).
    scope: Mapped[AreaScope] = mapped_column(Enum(AreaScope, name="area_scope"))
    system_prompt: Mapped[str | None] = mapped_column(Text)
    # Nombres del registro de herramientas en código (src/agents/tools.py); vacío si el área solo responde con FAQ.
    tools: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    active: Mapped[bool] = mapped_column(server_default="true")
