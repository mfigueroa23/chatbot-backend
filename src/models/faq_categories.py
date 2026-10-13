from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class FaqCategory(Base):
  __tablename__ = "faq_categories"
  __table_args__ = (
    UniqueConstraint("area_id", "name"),
  )

  id: Mapped[int] = mapped_column(primary_key=True)
  area_id: Mapped[int] = mapped_column(ForeignKey("areas.id", ondelete="CASCADE"))
  name: Mapped[str] = mapped_column(String(255))
