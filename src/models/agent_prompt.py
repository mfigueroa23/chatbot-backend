from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base

class AgentPrompt(Base):
    __tablename__ = "agent_prompt"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    content: Mapped[str] = mapped_column(Text)
