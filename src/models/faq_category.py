from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class FaqCategory(Base):
    __tablename__ = "faq_category"

    id: Mapped[int] = mapped_column(primary_key=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("business_area.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
