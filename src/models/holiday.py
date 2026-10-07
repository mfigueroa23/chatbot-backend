import datetime
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class Holiday(Base):
    __tablename__ = "holiday"

    date: Mapped[datetime.date] = mapped_column(primary_key=True)
    description: Mapped[str | None] = mapped_column(String(120))
