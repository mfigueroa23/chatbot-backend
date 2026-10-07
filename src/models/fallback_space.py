from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base
from src.models.business_area import AreaScope

class FallbackSpace(Base):
    """Space general de cada ámbito, para las consultas que no corresponden a ninguna área."""
    __tablename__ = "fallback_space"

    scope: Mapped[AreaScope] = mapped_column(Enum(AreaScope, name="area_scope"), primary_key=True)
    chat_space: Mapped[str] = mapped_column(String(255))
