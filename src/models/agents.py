from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class Agents(Base):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("area_id", name="uq_agents_area_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    prompt: Mapped[str] = mapped_column(Text)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id", name="fk_agents_area_id"))
