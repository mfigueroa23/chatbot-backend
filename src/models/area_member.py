from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class AreaMember(Base):
    """Colaborador habilitado para usar las herramientas de un área. Un área sin filas las ofrece a todo su canal."""
    __tablename__ = "area_member"

    area_id: Mapped[int] = mapped_column(ForeignKey("business_area.id", ondelete="CASCADE"), primary_key=True)
    # Correo de la cuenta de Google Chat, en minúsculas (spec 002, RF-1 y RF-4).
    email: Mapped[str] = mapped_column(String(255), primary_key=True)
