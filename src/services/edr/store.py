"""Lo que el trabajo del EDR lee y escribe en la BD: el EDR de la conversación (edr_document), su historial y el prompt de
redacción. Cada método abre su propia sesión: el trabajo corre después de que el mensaje cerró la suya (plan 003, D4)."""
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from langchain_core.messages import BaseMessage
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.agent_prompt import AgentPrompt
from src.models.conversation import Conversation
from src.models.edr_document import EdrDocumentRecord
from src.models.message import Message, MessageRole
from src.services.conversation import PgConversationStore
from src.utils.exceptions.database import DatabaseUnavailableError

@dataclass(frozen=True)
class EdrRecord:
    drive_file_id: str
    web_link: str
    title: str
    content: dict[str, Any]

class EdrRepository(Protocol):
    async def latest(self, conversation_id: uuid.UUID) -> EdrRecord | None: ...
    async def save(self, conversation_id: uuid.UUID, record: EdrRecord) -> None:
        """Actualiza la fila del mismo documento de Drive o crea una nueva (spec 003, RF-12)."""
        ...
    async def history(self, conversation_id: uuid.UUID, limit: int) -> list[BaseMessage]: ...
    async def append_reply(self, conversation_id: uuid.UUID, reply: str, now: datetime) -> None:
        """Suma al historial un mensaje del asistente publicado fuera de un turno (spec 003, RF-11)."""
        ...
    async def prompt(self, key: str) -> str | None: ...

class PgEdrRepository(EdrRepository):
    def __init__(self, session_factory: Callable[[], AsyncSession]):
        self._session_factory = session_factory

    async def latest(self, conversation_id: uuid.UUID) -> EdrRecord | None:
        statement = (select(EdrDocumentRecord).where(EdrDocumentRecord.conversation_id == conversation_id)
                     .order_by(EdrDocumentRecord.updated_at.desc(), EdrDocumentRecord.id.desc()).limit(1))
        try:
            async with self._session_factory() as session:
                row = await session.scalar(statement)
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc
        return EdrRecord(row.drive_file_id, row.web_link, row.title, row.content) if row is not None else None

    async def save(self, conversation_id: uuid.UUID, record: EdrRecord) -> None:
        try:
            async with self._session_factory() as session:
                row = await session.scalar(select(EdrDocumentRecord).where(
                    EdrDocumentRecord.conversation_id == conversation_id,
                    EdrDocumentRecord.drive_file_id == record.drive_file_id))
                if row is None:
                    session.add(EdrDocumentRecord(conversation_id=conversation_id, drive_file_id=record.drive_file_id,
                                                  web_link=record.web_link, title=record.title, content=record.content))
                else:
                    row.web_link, row.title, row.content = record.web_link, record.title, record.content
                await session.commit()
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc

    async def history(self, conversation_id: uuid.UUID, limit: int) -> list[BaseMessage]:
        async with self._session_factory() as session:
            return await PgConversationStore(session).history(conversation_id, limit)

    async def append_reply(self, conversation_id: uuid.UUID, reply: str, now: datetime) -> None:
        try:
            async with self._session_factory() as session:
                # La conversación pudo vencer y borrarse mientras se generaba el EDR: entonces no hay dónde guardarlo.
                if await session.get(Conversation, conversation_id) is None:
                    return
                session.add(Message(conversation_id=conversation_id, role=MessageRole.assistant, content=reply))
                await session.execute(update(Conversation).where(Conversation.id == conversation_id)
                                      .values(last_message_at=now))
                await session.commit()
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc

    async def prompt(self, key: str) -> str | None:
        try:
            async with self._session_factory() as session:
                return await session.scalar(select(AgentPrompt.content).where(AgentPrompt.key == key))
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc
