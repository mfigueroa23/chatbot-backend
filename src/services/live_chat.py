import uuid
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.live_chat import LiveChat, LiveChatStatus
from src.utils.exceptions.database import DatabaseUnavailableError

async def enqueue(session: AsyncSession, web_session_id: uuid.UUID, name: str, contact: str, question: str) -> LiveChat:
    chat = LiveChat(web_session_id=web_session_id, status=LiveChatStatus.waiting, customer_name=name,
                    customer_contact=contact, pending_question=question)
    try:
        # Savepoint: si la sesión ya tiene un chat abierto (índice único parcial) solo se deshace este INSERT.
        async with session.begin_nested():
            session.add(chat)
            await session.flush()
        return chat
    except IntegrityError:
        existing = await session.scalar(
            select(LiveChat).where(LiveChat.web_session_id == web_session_id, LiveChat.status != LiveChatStatus.closed))
        if existing is None:
            raise
        return existing
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc
