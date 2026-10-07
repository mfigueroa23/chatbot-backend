from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

EMBEDDING_DIMENSIONS = 768

class Faq(Base):
    __tablename__ = "faq"
    __table_args__ = (
        Index(
            "ix_faq_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("faq_category.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(server_default="true")
    # Lo calcula la BD: si el responsable edita la FAQ por SQL, el hash cambia y el embedding se recalcula.
    content_hash: Mapped[str] = mapped_column(Text, Computed("md5(question || E'\\n' || answer)", persisted=True))
    embedded_hash: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
