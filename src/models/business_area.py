from enum import StrEnum
from sqlalchemy import Enum, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class AreaScope(StrEnum):
    internal = "internal"
    external = "external"

class BusinessArea(Base):
    __tablename__ = "business_area"
    __table_args__ = (UniqueConstraint("scope", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    scope: Mapped[AreaScope] = mapped_column(Enum(AreaScope, name="area_scope"))
    system_prompt: Mapped[str | None] = mapped_column(Text)
    owner_email: Mapped[str | None] = mapped_column(String(320))
    active: Mapped[bool] = mapped_column(server_default="true")
