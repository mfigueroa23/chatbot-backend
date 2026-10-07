from datetime import datetime
from sqlalchemy import CHAR, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class ExecutiveSession(Base):
    __tablename__ = "executive_session"

    id: Mapped[int] = mapped_column(primary_key=True)
    executive_id: Mapped[int] = mapped_column(ForeignKey("executive.id", ondelete="CASCADE"))
    # Solo se guarda el sha256 del token: una fuga de la tabla no permite suplantar sesiones.
    token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
