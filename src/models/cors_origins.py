from sqlalchemy import Boolean, String, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class CorsOrigin(Base):
  __tablename__ = "cors_origins"
  __table_args__ = (
    UniqueConstraint("origin", name="uq_cors_origins_origin"),
  )

  id: Mapped[int] = mapped_column(primary_key=True)
  # Mismo texto que envía el navegador en Origin: esquema://host[:puerto], sin barra final.
  origin: Mapped[str] = mapped_column(String(255))
  enabled: Mapped[bool] = mapped_column(Boolean, server_default=true())
