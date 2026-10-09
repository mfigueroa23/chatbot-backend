from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class McpServer(Base):
    """Servidor MCP remoto (streamable HTTP). Se asigna a un área por nombre en business_area.mcp_servers."""
    __tablename__ = "mcp_server"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    url: Mapped[str] = mapped_column(String(500))
    # Nombre de la property con la credencial (Bearer); la credencial nunca se guarda aquí (spec 002, RF-12).
    credential_key: Mapped[str | None] = mapped_column(String(100))
    # Solo estas herramientas del servidor llegan al sub-agente; vacía = ninguna (plan 002, D9).
    allowed_tools: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    active: Mapped[bool] = mapped_column(server_default="true")
