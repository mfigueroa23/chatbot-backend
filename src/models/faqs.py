from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

EMBEDDING_DIMENSIONS = 768

class Faq(Base):
  __tablename__ = "faqs"
  __table_args__ = (
    UniqueConstraint("category_id", "question"),
    CheckConstraint("status IN ('index', 're-index')", name="ck_faqs_status"),
  )

  id: Mapped[int] = mapped_column(primary_key=True)
  category_id: Mapped[int] = mapped_column(ForeignKey("faq_categories.id", ondelete="CASCADE"))
  question: Mapped[str] = mapped_column(Text)
  answer: Mapped[str] = mapped_column(Text)
  embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
  status: Mapped[str] = mapped_column(String(20), server_default="re-index")
