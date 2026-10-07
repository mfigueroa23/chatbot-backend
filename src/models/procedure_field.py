from enum import StrEnum
from sqlalchemy import Enum, ForeignKey, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class FieldKind(StrEnum):
    text = "text"
    email = "email"
    phone = "phone"
    rut = "rut"
    number = "number"
    date = "date"

class ProcedureField(Base):
    __tablename__ = "procedure_field"
    __table_args__ = (UniqueConstraint("procedure_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    procedure_id: Mapped[int] = mapped_column(ForeignKey("procedure.id", ondelete="CASCADE"))
    # Clave del dato en la notificación; label es como se le pide al usuario.
    name: Mapped[str] = mapped_column(String(60))
    label: Mapped[str] = mapped_column(String(120))
    kind: Mapped[FieldKind] = mapped_column(Enum(FieldKind, name="field_kind"))
    position: Mapped[int] = mapped_column(SmallInteger, server_default="0")
