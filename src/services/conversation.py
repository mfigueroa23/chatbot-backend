"""Historial de cada sesión web y de cada conversación de Google Chat (plan, D8)."""
import logging
import uuid
from datetime import datetime
from typing import Protocol
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.conversation import Channel, Conversation
from src.models.message import Message, MessageRole
from src.utils.exceptions.database import DatabaseUnavailableError

logger = logging.getLogger(__name__)

class ConversationStore(Protocol):
    async def web_conversation(self, session_id: uuid.UUID | None, now: datetime) -> uuid.UUID:
        """La sesión indicada si existe; si no, una nueva (RF-18)."""
        ...
    async def chat_conversation(self, key: str, now: datetime) -> uuid.UUID: ...
    async def history(self, conversation_id: uuid.UUID, limit: int) -> list[BaseMessage]: ...
    async def append_turn(self, conversation_id: uuid.UUID, question: str, reply: str, now: datetime) -> None: ...
    async def delete_expired(self, cutoff: datetime) -> int: ...

class PgConversationStore(ConversationStore):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def web_conversation(self, session_id: uuid.UUID | None, now: datetime) -> uuid.UUID:
        try:
            if session_id is not None and await self._session.get(Conversation, session_id) is not None:
                return session_id
            conversation = Conversation(channel=Channel.web, last_message_at=now)
            self._session.add(conversation)
            # Se confirma ya: el cliente recibe este id aunque el modelo falle después.
            await self._session.commit()
            return conversation.id
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc

    async def chat_conversation(self, key: str, now: datetime) -> uuid.UUID:
        try:
            # Dos mensajes a la vez en el mismo hilo no chocan: el segundo encuentra la conversación ya creada.
            await self._session.execute(
                insert(Conversation).values(id=uuid.uuid4(), channel=Channel.google_chat, external_key=key,
                                            last_message_at=now)
                .on_conflict_do_nothing(index_elements=[Conversation.external_key]))
            conversation_id = await self._session.scalar(
                select(Conversation.id).where(Conversation.external_key == key))
            await self._session.commit()
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc
        if conversation_id is None:
            raise DatabaseUnavailableError(f"No se pudo crear la conversación de Google Chat {key}")
        return conversation_id

    async def history(self, conversation_id: uuid.UUID, limit: int) -> list[BaseMessage]:
        try:
            rows = (await self._session.execute(
                select(Message.role, Message.content).where(Message.conversation_id == conversation_id)
                .order_by(Message.id.desc()).limit(limit))).all()
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc
        return [HumanMessage(row.content) if row.role == MessageRole.user else AIMessage(row.content)
                for row in reversed(rows)]

    async def append_turn(self, conversation_id: uuid.UUID, question: str, reply: str, now: datetime) -> None:
        try:
            self._session.add_all([Message(conversation_id=conversation_id, role=MessageRole.user, content=question),
                                   Message(conversation_id=conversation_id, role=MessageRole.assistant, content=reply)])
            await self._session.execute(update(Conversation).where(Conversation.id == conversation_id)
                                        .values(last_message_at=now))
            await self._session.commit()
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc

    async def delete_expired(self, cutoff: datetime) -> int:
        try:
            result = await self._session.execute(delete(Conversation).where(Conversation.last_message_at < cutoff))
            await self._session.commit()
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc
        deleted = getattr(result, "rowcount", 0) or 0
        logger.info("Se borraron %s conversaciones sin mensajes desde %s", deleted, cutoff.isoformat())
        return deleted
