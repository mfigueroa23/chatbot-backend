import logging
from datetime import timedelta
from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.database.session import SessionDep, SessionFactoryDep, commit
from src.interfaces.executive import (
    AssignedChats, CustomerText, ExecutiveAuth, ExecutiveChatClosed, ExecutivePing, LoginRequest, LoginResponse,
    executive_message_adapter)
from src.interfaces.live_chat import ChatSummary
from src.models.executive import Executive
from src.models.live_chat_message import MessageSender
from src.services.executive_auth import (
    ExecutiveRepository, SqlExecutiveRepository, authenticate, load_auth_settings, login, logout)
from src.services.live_chat import (
    executive_heartbeat, get_assigned_chat, get_message, mark_executive_disconnected, post_message, resume)
from src.services.property import get_int_property
from src.services.realtime import ConnectionHub, Event, get_hub
from src.utils.clock import Clock, get_clock
from src.utils.exceptions.auth import AccountLockedError, InvalidCredentialsError, InvalidSessionError
from src.utils.exceptions.database import DatabaseUnavailableError

router = APIRouter(tags=["Ejecutivos"])
logger = logging.getLogger(__name__)

INVALID_CREDENTIALS = "Usuario o contraseña incorrectos"

def get_executive_repository(session: SessionDep) -> ExecutiveRepository:
    return SqlExecutiveRepository(session)

RepositoryDep = Annotated[ExecutiveRepository, Depends(get_executive_repository)]
ClockDep = Annotated[Clock, Depends(get_clock)]
HubDep = Annotated[ConnectionHub, Depends(get_hub)]

def bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión no válida")
    return authorization.removeprefix("Bearer ")

async def get_current_executive(
    repo: RepositoryDep, clock: ClockDep, authorization: Annotated[str | None, Header()] = None
) -> Executive:
    try:
        return await authenticate(repo, clock, bearer_token(authorization))
    except InvalidSessionError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión no válida") from exc
    except DatabaseUnavailableError as exc:
        logger.error("Autenticación de ejecutivo: base de datos no disponible (%s)", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Servicio no disponible") from exc

CurrentExecutive = Annotated[Executive, Depends(get_current_executive)]

@router.post("/api/v1/executives/login", responses={401: {}, 503: {}})
async def executive_login(body: LoginRequest, session: SessionDep, repo: RepositoryDep, clock: ClockDep) -> LoginResponse:
    try:
        logger.debug("Login de ejecutivo iniciado")
        token = await login(repo, clock, await load_auth_settings(session), body.username, body.password)
        return LoginResponse(token=token.token, expires_at=token.expires_at)
    except (InvalidCredentialsError, AccountLockedError) as exc:
        # El mismo mensaje para todo: no se revela si el usuario existe o está bloqueado.
        logger.warning("Login de ejecutivo rechazado: %s", type(exc).__name__)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID_CREDENTIALS) from exc
    except DatabaseUnavailableError as exc:
        logger.error("Login de ejecutivo: base de datos no disponible (%s)", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Servicio no disponible") from exc

@router.post("/api/v1/executives/logout", status_code=status.HTTP_204_NO_CONTENT, responses={401: {}, 503: {}})
async def executive_logout(
    executive: CurrentExecutive, repo: RepositoryDep, authorization: Annotated[str | None, Header()] = None
) -> None:
    try:
        await logout(repo, bearer_token(authorization))
    except DatabaseUnavailableError as exc:
        logger.error("Logout de ejecutivo: base de datos no disponible (%s)", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Servicio no disponible") from exc

CLOSE_UNAUTHORIZED = 4401
CLOSE_INTERNAL_ERROR = 1011

@router.websocket("/ws/v1/executive")
async def executive_ws(websocket: WebSocket, session_factory: SessionFactoryDep, clock: ClockDep, hub: HubDep) -> None:
    await websocket.accept()
    try:
        token = ExecutiveAuth.model_validate(await websocket.receive_json()).token
        async with session_factory() as session:
            executive = await authenticate(SqlExecutiveRepository(session), clock, token)
            window = timedelta(minutes=await get_int_property(session, "executive_reconnect_minutes", 60))
            chats = await resume(session, executive.id, clock.now(), window)
            await commit(session)
    except (ValidationError, InvalidSessionError):
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return
    except DatabaseUnavailableError as exc:
        logger.error("WebSocket de ejecutivo: base de datos no disponible al conectar (%s)", exc)
        await websocket.close(code=CLOSE_INTERNAL_ERROR)
        return

    executive_id = executive.id

    async def deliver(event: Event) -> None:
        if event.kind == "customer_message" and event.message_id is not None:
            async with session_factory() as session:
                message = await get_message(session, event.message_id)
            if message is not None:
                await send(websocket, CustomerText(chat_id=event.chat_id, text=message.content))
        elif event.kind == "chat_closed":
            await send(websocket, ExecutiveChatClosed(chat_id=event.chat_id, reason=event.reason or ""))

    hub.register_executive(executive_id, deliver)
    await send(websocket, AssignedChats(chats=[ChatSummary.from_chat(chat) for chat in chats]))
    try:
        while True:
            raw = await websocket.receive_json()
            try:
                message = executive_message_adapter.validate_python(raw)
            except ValidationError:
                logger.warning("WebSocket de ejecutivo: mensaje con formato no válido descartado")
                continue
            async with session_factory() as session:
                # La sesión puede caducar en mitad de un chat: se trata como una desconexión del ejecutivo.
                await authenticate(SqlExecutiveRepository(session), clock, token)
                if isinstance(message, ExecutivePing):
                    await executive_heartbeat(session, executive_id, clock.now())
                else:
                    await forward_to_customer(session, hub, executive_id, message.chat_id, message.text)
                await commit(session)
    except InvalidSessionError:
        logger.info("La sesión del ejecutivo %s caducó durante el chat", executive_id)
        await websocket.close(code=CLOSE_UNAUTHORIZED)
    except WebSocketDisconnect:
        logger.debug("El ejecutivo %s se desconectó", executive_id)
    except DatabaseUnavailableError as exc:
        logger.error("WebSocket de ejecutivo: base de datos no disponible (%s)", exc)
        await websocket.close(code=CLOSE_INTERNAL_ERROR)
    finally:
        hub.unregister_executive(executive_id)
        await notify_executive_disconnected(session_factory, hub, executive_id, clock)

async def forward_to_customer(session: AsyncSession, hub: ConnectionHub, executive_id: int, chat_id: int, text: str) -> None:
    chat = await get_assigned_chat(session, chat_id, executive_id)
    if chat is None or not text.strip():
        return
    message = await post_message(session, chat.id, MessageSender.executive, text)
    await hub.publish(session, Event("executive_message", chat.id, web_session_id=str(chat.web_session_id),
                                     executive_id=executive_id, message_id=message.id))

async def notify_executive_disconnected(
    session_factory: async_sessionmaker[AsyncSession], hub: ConnectionHub, executive_id: int, clock: Clock
) -> None:
    try:
        async with session_factory() as session:
            for chat in await mark_executive_disconnected(session, executive_id, clock.now()):
                await hub.publish(session, Event("executive_disconnected", chat.id, web_session_id=str(chat.web_session_id),
                                                 executive_id=executive_id))
            await commit(session)
    except DatabaseUnavailableError as exc:
        logger.error("No se pudo registrar la desconexión del ejecutivo %s (%s)", executive_id, exc)

async def send(websocket: WebSocket, message: BaseModel) -> None:
    await websocket.send_json(message.model_dump(mode="json"))
