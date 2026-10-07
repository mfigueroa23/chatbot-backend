from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class Property(Base):
    __tablename__ = "property"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(255), unique=True)
    value: Mapped[str] = mapped_column(Text)
