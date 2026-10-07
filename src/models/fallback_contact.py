from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base
from src.models.business_area import AreaScope

class FallbackContact(Base):
    __tablename__ = "fallback_contact"

    scope: Mapped[AreaScope] = mapped_column(Enum(AreaScope, name="area_scope"), primary_key=True)
    email: Mapped[str] = mapped_column(String(320))
