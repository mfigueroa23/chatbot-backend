from sqlalchemy  import CheckConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class Area(Base):
  __tablename__ = "areas"
  __table_args__ = (
    CheckConstraint("audiencia IN ('externo', 'interno')", name="ck_areas_audiencia"),
  )

  id: Mapped[int] = mapped_column(primary_key = True)
  name: Mapped[str] = mapped_column(String(255), unique = True)
  description: Mapped[str] = mapped_column(Text)
  audiencia: Mapped[str] = mapped_column(String(20))
