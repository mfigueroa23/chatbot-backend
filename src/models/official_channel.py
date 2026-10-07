from sqlalchemy import SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class OfficialChannel(Base):
    __tablename__ = "official_channel"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(80))
    value: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(SmallInteger, server_default="0")
