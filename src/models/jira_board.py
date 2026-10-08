from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class JiraBoard(Base):
    """Tablero (proyecto) de Jira que el asistente puede consultar; fuera de esta lista no busca ni lee tickets."""
    __tablename__ = "jira_board"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(20), unique=True)  # p. ej. DAIA
    active: Mapped[bool] = mapped_column(server_default="true")
