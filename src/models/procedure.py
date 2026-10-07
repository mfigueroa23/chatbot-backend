from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base
from src.models.faq import EMBEDDING_DIMENSIONS

class Procedure(Base):
    __tablename__ = "procedure"
    __table_args__ = (
        Index(
            "ix_procedure_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("business_area.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    # Lo que se explica al usuario: los pasos que seguirá el área.
    steps: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(server_default="true")
    # Como en las FAQ: si el responsable edita el procedimiento por SQL, el hash cambia y el embedding se recalcula.
    content_hash: Mapped[str] = mapped_column(Text, Computed("md5(name || E'\\n' || steps)", persisted=True))
    embedded_hash: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
