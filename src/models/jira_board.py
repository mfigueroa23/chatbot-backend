from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class JiraBoard(Base):
    """Proyecto de Jira en el que el asistente puede buscar y leer tickets (spec 002, RF-18 y RF-19)."""
    __tablename__ = "jira_board"

    key: Mapped[str] = mapped_column(String(20), primary_key=True)
    active: Mapped[bool] = mapped_column(server_default="true")
