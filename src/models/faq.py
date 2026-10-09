from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

# Cambiar de modelo de embeddings a otra dimensión requiere una migración y recalcular todas las FAQ.
EMBEDDING_DIMENSIONS = 768

class Faq(Base):
    # Sin índice vectorial: con cientos de FAQ la búsqueda exacta filtrada por área tarda milisegundos (plan, D11).
    __tablename__ = "faq"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("faq_category.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(server_default="true")
    # Lo calcula la BD: si el responsable edita la FAQ por SQL, el hash cambia y el embedding se recalcula (RF-24).
    content_hash: Mapped[str] = mapped_column(Text, Computed("md5(question || E'\\n' || answer)", persisted=True))
    embedded_hash: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
