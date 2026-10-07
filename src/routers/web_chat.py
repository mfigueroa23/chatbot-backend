import logging
import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker
from src.database.session import SessionFactoryDep, commit
from src.interfaces.web_chat import (
    Busy, Channel, ChatClosed, ContactMessage, ErrorMessage, ExecutiveDisconnected, ExecutiveJoined, HumanResponse, Ping,
    RequestHuman, ServerMessage, SessionStarted, TextMessage, UserMessage, client_message_adapter)
from src.models.live_chat import LiveChatStatus
from src.models.live_chat_message import MessageSender
from src.models.web_session import WebPhase
from src.services.business_data import get_official_channels
from src.services.chat_orchestrator import (
    EMPTY_MESSAGE, TOO_LONG_MESSAGE, UNAVAILABLE, handle_contact, handle_human_response, handle_request_human,
    handle_web_message)
from src.services.live_chat import customer_disconnected, get_message, get_open_chat, post_message
from src.services.message_validation import validate_user_message
from src.services.property import get_int_property
from src.services.realtime import ConnectionHub, Event, get_hub
from src.services.web_session import admit, get_or_create, get_web_session, heartbeat, mark_disconnected
from src.utils.exceptions.message import EmptyMessageError, MessageTooLongError
from src.utils.clock import Clock, get_clock
from src.utils.exceptions.database import DatabaseUnavailableError

router = APIRouter(tags=["Chat web"])
logger = logging.getLogger(__name__)

ClockDep = Annotated[Clock, Depends(get_clock)]
HubDep = Annotated[ConnectionHub, Depends(get_hub)]
# Cierres en los que el cliente debe ver los canales oficiales para seguir siendo atendido.
CLOSE_REASONS_WITH_CHANNELS = {"executive_timeout", "schedule_end"}
CLOSE_TRY_AGAIN_LATER = 1013
CLOSE_INTERNAL_ERROR = 1011

async def send(websocket: WebSocket, message: BaseModel) -> None:
    await websocket.send_json(message.model_dump(mode="json", by_alias=True, exclude_none=True))

@router.websocket("/ws/v1/chat")
async def web_chat(
    websocket: WebSocket, session_factory: SessionFactoryDep, clock: ClockDep, hub: HubDep, session_id: uuid.UUID | None = None
) -> None:
    await websocket.accept()
    try:
        async with session_factory() as session:
            retention_days = await get_int_property(session, "web_session_retention_days", 30)
            max_sessions = await get_int_property(session, "web_max_sessions", 50)
            web_session = await get_or_create(session, clock, session_id, retention_days)
            current_id = web_session.id
            if not await admit(session, clock, current_id, max_sessions):
                logger.warning("Chat web rechazado: se alcanzó el máximo de %s sesiones activas", max_sessions)
                channels = await get_official_channels(session)
                await send(websocket, Busy(channels=[Channel(label=c.label, value=c.value) for c in channels]))
                await websocket.close(code=CLOSE_TRY_AGAIN_LATER)
                return
    except DatabaseUnavailableError as exc:
        logger.error("Chat web: base de datos no disponible al conectar (%s)", exc)
        await send(websocket, ErrorMessage(code="service_unavailable", text=UNAVAILABLE))
        await websocket.close(code=CLOSE_INTERNAL_ERROR)
        return

    await send(websocket, SessionStarted(session_id=current_id))

    async def deliver(event: Event) -> None:
        await send(websocket, await customer_event_message(session_factory, event))

    hub.register_customer(str(current_id), deliver)
    try:
        while True:
            raw = await websocket.receive_json()
            try:
                message = client_message_adapter.validate_python(raw)
            except ValidationError:
                logger.warning("Chat web: mensaje con formato no válido descartado")
                continue
            async with session_factory() as session:
                replies = await dispatch(websocket, session, hub, current_id, message, clock)
            # Si el cliente se desconectó mientras se generaba la respuesta, el envío falla y la respuesta se descarta.
            for reply in replies:
                await send(websocket, reply)
    except WebSocketDisconnect:
        logger.debug("Chat web: el cliente %s se desconectó", current_id)
    finally:
        hub.unregister_customer(str(current_id))
        await notify_customer_disconnected(session_factory, hub, current_id, clock)

async def notify_customer_disconnected(
    session_factory: async_sessionmaker[AsyncSession], hub: ConnectionHub, session_id: uuid.UUID, clock: Clock
) -> None:
    try:
        async with session_factory() as session:
            await mark_disconnected(session, session_id)
            # Si tenía un chat en espera sale de la cola; si estaba asignado se cierra y se avisa al ejecutivo.
            chat = await customer_disconnected(session, session_id, clock.now())
            if chat is not None and chat.executive_id is not None:
                await hub.publish(session, Event("chat_closed", chat.id, web_session_id=str(session_id),
                                                 executive_id=chat.executive_id, reason="customer_left"))
            await commit(session)
    except DatabaseUnavailableError as exc:
        logger.error("Chat web: no se pudo registrar la desconexión de la sesión %s (%s)", session_id, exc)

async def customer_event_message(session_factory: async_sessionmaker[AsyncSession], event: Event) -> ServerMessage:
    async with session_factory() as session:
        match event.kind:
            case "chat_taken":
                return ExecutiveJoined()
            case "executive_message" if event.message_id is not None:
                message = await get_message(session, event.message_id)
                return TextMessage(from_="executive", text=message.content if message else "")
            case "executive_disconnected":
                minutes = await get_int_property(session, "executive_reconnect_minutes", 60)
                return ExecutiveDisconnected(return_within_minutes=minutes)
            case _:
                reason = event.reason or ""
                channels = None
                if reason in CLOSE_REASONS_WITH_CHANNELS:
                    channels = [Channel(label=c.label, value=c.value) for c in await get_official_channels(session)]
                return ChatClosed(reason=reason, channels=channels)

async def dispatch(
    websocket: WebSocket, session: AsyncSession, hub: ConnectionHub, session_id: uuid.UUID, message, clock: Clock
) -> list[ServerMessage]:
    try:
        if isinstance(message, Ping):
            await heartbeat(session, clock, session_id)
            return []
        web_session = await get_web_session(session, session_id)
        if web_session is None:
            raise DatabaseUnavailableError(f"La sesión web {session_id} ya no existe")
        match message:
            case UserMessage() if web_session.phase == WebPhase.live:
                # Con un ejecutivo asignado el agente no responde: el mensaje va al ejecutivo.
                return await forward_to_executive(session, hub, session_id, message.text)
            case UserMessage():
                return await handle_web_message(session, websocket.app.state.external_graph, web_session, message.text, clock)
            case HumanResponse():
                return await handle_human_response(session, web_session, message.accept)
            case ContactMessage():
                return await handle_contact(session, web_session, message.name, message.email, message.phone)
            case RequestHuman():
                return await handle_request_human(session, web_session, clock)
        return []
    except DatabaseUnavailableError as exc:
        logger.error("Chat web: base de datos no disponible (%s)", exc)
        return [ErrorMessage(code="service_unavailable", text=UNAVAILABLE)]

async def forward_to_executive(session: AsyncSession, hub: ConnectionHub, session_id: uuid.UUID, text: str) -> list[ServerMessage]:
    try:
        text = validate_user_message(text)
    except EmptyMessageError:
        return [ErrorMessage(code="empty_message", text=EMPTY_MESSAGE)]
    except MessageTooLongError:
        return [ErrorMessage(code="message_too_long", text=TOO_LONG_MESSAGE)]
    chat = await get_open_chat(session, session_id)
    if chat is None or chat.status != LiveChatStatus.assigned or chat.executive_id is None:
        return []
    message = await post_message(session, chat.id, MessageSender.customer, text)
    await hub.publish(session, Event("customer_message", chat.id, web_session_id=str(session_id),
                                     executive_id=chat.executive_id, message_id=message.id))
    await commit(session)
    return []
