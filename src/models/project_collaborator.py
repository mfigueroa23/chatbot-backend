from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class ProjectCollaborator(Base):
    """Colaborador habilitado para consultar Jira y generar EDR, identificado por su correo de Google Chat."""
    __tablename__ = "project_collaborator"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Se guarda en minúsculas: Google Chat puede entregar el correo con otra capitalización.
    email: Mapped[str] = mapped_column(String(255), unique=True)
    active: Mapped[bool] = mapped_column(server_default="true")
