import logging
import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from src.database.session import SessionFactoryDep
from src.interfaces.web_chat import (
    Busy, Channel, ContactMessage, ErrorMessage, HumanResponse, Ping, RequestHuman, ServerMessage, SessionStarted,
    UserMessage, client_message_adapter)
from src.services.business_data import get_official_channels
from src.services.chat_orchestrator import (
    UNAVAILABLE, handle_contact, handle_human_response, handle_request_human, handle_web_message)
from src.services.property import get_int_property
from src.services.web_session import admit, get_or_create, get_web_session, heartbeat, mark_disconnected
from src.utils.clock import Clock, get_clock
from src.utils.exceptions.database import DatabaseUnavailableError

router = APIRouter(tags=["Chat web"])
logger = logging.getLogger(__name__)

ClockDep = Annotated[Clock, Depends(get_clock)]
CLOSE_TRY_AGAIN_LATER = 1013
CLOSE_INTERNAL_ERROR = 1011

async def send(websocket: WebSocket, message: BaseModel) -> None:
    await websocket.send_json(message.model_dump(mode="json", by_alias=True, exclude_none=True))

@router.websocket("/ws/v1/chat")
async def web_chat(websocket: WebSocket, session_factory: SessionFactoryDep, clock: ClockDep, session_id: uuid.UUID | None = None) -> None:
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
    try:
        while True:
            raw = await websocket.receive_json()
            try:
                message = client_message_adapter.validate_python(raw)
            except ValidationError:
                logger.warning("Chat web: mensaje con formato no válido descartado")
                continue
            async with session_factory() as session:
                replies = await dispatch(websocket, session, current_id, message, clock)
            # Si el cliente se desconectó mientras se generaba la respuesta, el envío falla y la respuesta se descarta.
            for reply in replies:
                await send(websocket, reply)
    except WebSocketDisconnect:
        logger.debug("Chat web: el cliente %s se desconectó", current_id)
    finally:
        try:
            async with session_factory() as session:
                await mark_disconnected(session, current_id)
        except DatabaseUnavailableError as exc:
            logger.error("Chat web: no se pudo marcar la sesión %s como desconectada (%s)", current_id, exc)

async def dispatch(websocket: WebSocket, session: AsyncSession, session_id: uuid.UUID, message, clock: Clock) -> list[ServerMessage]:
    try:
        if isinstance(message, Ping):
            await heartbeat(session, clock, session_id)
            return []
        web_session = await get_web_session(session, session_id)
        if web_session is None:
            raise DatabaseUnavailableError(f"La sesión web {session_id} ya no existe")
        match message:
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
