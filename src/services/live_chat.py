import uuid
from datetime import datetime, timedelta
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.executive import Executive
from src.models.live_chat import CloseReason, LiveChat, LiveChatStatus
from src.models.live_chat_message import LiveChatMessage, MessageSender
from src.models.web_session import WebPhase, WebSession
from src.utils.exceptions.database import DatabaseUnavailableError
from src.utils.exceptions.live_chat import (
    ChatAlreadyAssignedError, ChatNotFoundError, ExecutiveChatLimitError, NotChatOwnerError)

# --- Dominio: transiciones puras, sin BD ---------------------------------------------------------------------------

def take_chat(chat: LiveChat, executive_id: int, assigned_count: int, max_chats: int, now: datetime) -> None:
    if chat.status != LiveChatStatus.waiting:
        raise ChatAlreadyAssignedError()
    if assigned_count >= max_chats:
        raise ExecutiveChatLimitError()
    chat.status = LiveChatStatus.assigned
    chat.executive_id = executive_id
    chat.assigned_at = now

def executive_left(chat: LiveChat, now: datetime) -> None:
    if chat.status == LiveChatStatus.assigned and chat.executive_disconnected_at is None:
        chat.executive_disconnected_at = now

def executive_timed_out(chat: LiveChat, now: datetime, window: timedelta) -> bool:
    return (chat.status == LiveChatStatus.assigned and chat.executive_disconnected_at is not None
            and now - chat.executive_disconnected_at >= window)

def resume_chat(chat: LiveChat, now: datetime, window: timedelta) -> bool:
    if chat.status != LiveChatStatus.assigned or executive_timed_out(chat, now, window):
        return False
    chat.executive_disconnected_at = None
    return True

def close_chat(chat: LiveChat, reason: CloseReason, now: datetime) -> None:
    chat.status = LiveChatStatus.closed
    chat.close_reason = reason
    chat.closed_at = now

def customer_left(chat: LiveChat, now: datetime) -> None:
    # En espera: sale de la cola. Asignado: se cierra y se avisa al ejecutivo.
    if chat.status != LiveChatStatus.closed:
        close_chat(chat, CloseReason.customer_left, now)

def close_by_executive(chat: LiveChat, executive_id: int, now: datetime) -> None:
    if chat.status != LiveChatStatus.assigned or chat.executive_id != executive_id:
        raise NotChatOwnerError()
    close_chat(chat, CloseReason.executive, now)

# --- SQL -----------------------------------------------------------------------------------------------------------

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
        existing = await get_open_chat(session, web_session_id)
        if existing is None:
            raise
        return existing
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc

async def take(session: AsyncSession, chat_id: int, executive_id: int, max_chats: int, now: datetime) -> LiveChat:
    try:
        # Bloquear la fila del ejecutivo serializa sus tomas: dos tomas simultáneas no superan su máximo.
        await session.execute(select(Executive.id).where(Executive.id == executive_id).with_for_update())
        assigned = await session.scalar(select(func.count()).select_from(LiveChat).where(
            LiveChat.executive_id == executive_id, LiveChat.status == LiveChatStatus.assigned))
        if (assigned or 0) >= max_chats:
            raise ExecutiveChatLimitError()
        # El WHERE status = 'waiting' hace la toma atómica: si dos ejecutivos toman a la vez, solo uno actualiza.
        chat = await session.scalar(
            update(LiveChat)
            .where(LiveChat.id == chat_id, LiveChat.status == LiveChatStatus.waiting)
            .values(status=LiveChatStatus.assigned, executive_id=executive_id, assigned_at=now)
            .returning(LiveChat)
        )
        if chat is None:
            status = await session.scalar(select(LiveChat.status).where(LiveChat.id == chat_id))
            if status is None or status == LiveChatStatus.closed:
                raise ChatNotFoundError()
            raise ChatAlreadyAssignedError()
        await set_phase(session, chat.web_session_id, WebPhase.live)
        return chat
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc

async def list_waiting(session: AsyncSession) -> list[LiveChat]:
    try:
        return list(await session.scalars(
            select(LiveChat).where(LiveChat.status == LiveChatStatus.waiting).order_by(LiveChat.created_at, LiveChat.id)))
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc

async def get_open_chat(session: AsyncSession, web_session_id: uuid.UUID) -> LiveChat | None:
    try:
        return await session.scalar(select(LiveChat).where(
            LiveChat.web_session_id == web_session_id, LiveChat.status != LiveChatStatus.closed).with_for_update())
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc

async def get_assigned_chat(session: AsyncSession, chat_id: int, executive_id: int) -> LiveChat | None:
    try:
        return await session.scalar(select(LiveChat).where(
            LiveChat.id == chat_id, LiveChat.executive_id == executive_id, LiveChat.status == LiveChatStatus.assigned))
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc

async def post_message(session: AsyncSession, chat_id: int, sender: MessageSender, content: str) -> LiveChatMessage:
    message = LiveChatMessage(live_chat_id=chat_id, sender=sender, content=content)
    try:
        session.add(message)
        await session.flush()
        return message
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc

async def get_message(session: AsyncSession, message_id: int) -> LiveChatMessage | None:
    try:
        return await session.get(LiveChatMessage, message_id)
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc

async def close(session: AsyncSession, chat_id: int, executive_id: int, now: datetime) -> LiveChat:
    try:
        chat = await session.scalar(select(LiveChat).where(LiveChat.id == chat_id).with_for_update())
        if chat is None or chat.status == LiveChatStatus.closed:
            raise ChatNotFoundError()
        close_by_executive(chat, executive_id, now)
        await set_phase(session, chat.web_session_id, WebPhase.bot)
        return chat
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc

async def customer_disconnected(session: AsyncSession, web_session_id: uuid.UUID, now: datetime) -> LiveChat | None:
    chat = await get_open_chat(session, web_session_id)
    if chat is None:
        return None
    customer_left(chat, now)
    await set_phase(session, web_session_id, WebPhase.bot)
    return chat

async def mark_executive_disconnected(session: AsyncSession, executive_id: int, now: datetime) -> list[LiveChat]:
    try:
        chats = list(await session.scalars(
            update(LiveChat)
            .where(LiveChat.executive_id == executive_id, LiveChat.status == LiveChatStatus.assigned,
                   LiveChat.executive_disconnected_at.is_(None))
            .values(executive_disconnected_at=now)
            .returning(LiveChat)
        ))
        await session.execute(update(Executive).where(Executive.id == executive_id).values(connected=False))
        return chats
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc

async def resume(session: AsyncSession, executive_id: int, now: datetime, window: timedelta) -> list[LiveChat]:
    try:
        await session.execute(
            update(LiveChat)
            .where(LiveChat.executive_id == executive_id, LiveChat.status == LiveChatStatus.assigned,
                   LiveChat.executive_disconnected_at > now - window)
            .values(executive_disconnected_at=None)
        )
        await executive_heartbeat(session, executive_id, now)
        return list(await session.scalars(select(LiveChat).where(
            LiveChat.executive_id == executive_id, LiveChat.status == LiveChatStatus.assigned,
            LiveChat.executive_disconnected_at.is_(None)).order_by(LiveChat.assigned_at)))
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc

async def executive_heartbeat(session: AsyncSession, executive_id: int, now: datetime) -> None:
    try:
        await session.execute(update(Executive).where(Executive.id == executive_id).values(connected=True, last_seen_at=now))
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc

async def set_phase(session: AsyncSession, web_session_id: uuid.UUID, phase: WebPhase) -> None:
    try:
        await session.execute(update(WebSession).where(WebSession.id == web_session_id).values(phase=phase))
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc
