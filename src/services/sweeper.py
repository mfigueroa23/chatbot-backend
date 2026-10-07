import asyncio
import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Protocol
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.models.executive import Executive
from src.models.live_chat import CloseReason, LiveChat, LiveChatStatus
from src.models.web_session import WebPhase, WebSession
from src.services.live_chat import close_chat, executive_timed_out, mark_executive_disconnected, set_phase
from src.services.property import get_int_property
from src.services.realtime import ConnectionHub, Event
from src.services.schedule import Slots, is_open, load_schedule
from src.services.web_session import HEARTBEAT_TIMEOUT
from src.utils.clock import Clock
from src.utils.exceptions.database import DatabaseUnavailableError

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = 30
SWEEP_LOCK_ID = 727_100_003

class Checkpointer(Protocol):
    async def adelete_thread(self, thread_id: str) -> None: ...

# --- Decisiones: funciones puras -----------------------------------------------------------------------------------

def chats_to_close_at_schedule_end(chats: list[LiveChat], now: datetime, slots: Slots, holidays: set[date]) -> list[LiveChat]:
    # Los chats ya asignados siguen abiertos aunque termine el horario; solo se vacía la cola.
    if is_open(now, slots, holidays):
        return []
    return [chat for chat in chats if chat.status == LiveChatStatus.waiting]

def timed_out_chats(chats: list[LiveChat], now: datetime, window: timedelta) -> list[LiveChat]:
    return [chat for chat in chats if executive_timed_out(chat, now, window)]

def is_stale(last_seen_at: datetime | None, now: datetime) -> bool:
    return last_seen_at is None or now - last_seen_at > HEARTBEAT_TIMEOUT

def is_expired(web_session: WebSession, now: datetime, retention_days: int) -> bool:
    return web_session.last_message_at <= now - timedelta(days=retention_days)

# --- Ejecución -----------------------------------------------------------------------------------------------------

async def run_sweep(session: AsyncSession, clock: Clock, hub: ConnectionHub, checkpointer: Checkpointer) -> bool:
    try:
        # Solo un pod barre en cada vuelta; el lock de transacción se libera solo con el commit.
        if not await session.scalar(select(func.pg_try_advisory_xact_lock(SWEEP_LOCK_ID))):
            return False
        now = clock.now()
        await close_waiting_chats(session, hub, now)
        await close_timed_out_chats(session, hub, now)
        await disconnect_stale(session, hub, now)
        retention_days = await get_int_property(session, "web_session_retention_days", 30)
        expired = await expired_session_ids(session, now, retention_days)
        for session_id in expired:
            await checkpointer.adelete_thread(str(session_id))
        if expired:
            # El borrado en cascada se lleva también sus chats en vivo y mensajes.
            await session.execute(delete(WebSession).where(WebSession.id.in_(expired)))
        await session.commit()
        return True
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc

async def close_waiting_chats(session: AsyncSession, hub: ConnectionHub, now: datetime) -> None:
    slots, holidays = await load_schedule(session)
    waiting = list(await session.scalars(select(LiveChat).where(LiveChat.status == LiveChatStatus.waiting).with_for_update()))
    for chat in chats_to_close_at_schedule_end(waiting, now, slots, holidays):
        await close_and_notify(session, hub, chat, CloseReason.schedule_end, now)

async def close_timed_out_chats(session: AsyncSession, hub: ConnectionHub, now: datetime) -> None:
    window = timedelta(minutes=await get_int_property(session, "executive_reconnect_minutes", 60))
    disconnected = list(await session.scalars(select(LiveChat).where(
        LiveChat.status == LiveChatStatus.assigned, LiveChat.executive_disconnected_at.is_not(None)).with_for_update()))
    for chat in timed_out_chats(disconnected, now, window):
        await close_and_notify(session, hub, chat, CloseReason.executive_timeout, now)

async def close_and_notify(session: AsyncSession, hub: ConnectionHub, chat: LiveChat, reason: CloseReason, now: datetime) -> None:
    close_chat(chat, reason, now)
    await set_phase(session, chat.web_session_id, WebPhase.bot)
    await hub.publish(session, Event("chat_closed", chat.id, web_session_id=str(chat.web_session_id),
                                     executive_id=chat.executive_id, reason=reason.value))
    logger.info("Chat %s cerrado por %s", chat.id, reason.value)

async def disconnect_stale(session: AsyncSession, hub: ConnectionHub, now: datetime) -> None:
    # Un pod que muere no avisa del cierre de sus sockets: sin heartbeat reciente se dan por desconectados.
    threshold = now - HEARTBEAT_TIMEOUT
    await session.execute(update(WebSession).where(WebSession.connected, WebSession.last_seen_at < threshold).values(connected=False))
    stale_executives = list(await session.scalars(select(Executive.id).where(
        Executive.connected, (Executive.last_seen_at < threshold) | Executive.last_seen_at.is_(None))))
    for executive_id in stale_executives:
        for chat in await mark_executive_disconnected(session, executive_id, now):
            await hub.publish(session, Event("executive_disconnected", chat.id, web_session_id=str(chat.web_session_id),
                                             executive_id=executive_id))

async def expired_session_ids(session: AsyncSession, now: datetime, retention_days: int) -> list[uuid.UUID]:
    return list(await session.scalars(select(WebSession.id).where(
        WebSession.last_message_at <= now - timedelta(days=retention_days))))

async def sweep_forever(
    session_factory: async_sessionmaker[AsyncSession], clock: Clock, hub: ConnectionHub, checkpointer: Checkpointer
) -> None:
    while True:
        # Se espera antes de la primera vuelta: un arranque corto (o un test) no toca la BD.
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        try:
            async with session_factory() as session:
                await run_sweep(session, clock, hub, checkpointer)
        except DatabaseUnavailableError as exc:
            logger.error("Barrido periódico: base de datos no disponible (%s)", exc)
        except Exception:
            logger.exception("Barrido periódico falló por un error inesperado")
