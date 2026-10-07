import logging
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException, status
from src.database.session import SessionDep, commit
from src.interfaces.live_chat import ChatSummary, WaitingChat
from src.routers.executive import CurrentExecutive
from src.services.live_chat import close, list_waiting, take
from src.services.property import get_int_property
from src.services.realtime import ConnectionHub, Event, get_hub
from src.utils.clock import Clock, get_clock
from src.utils.exceptions.database import DatabaseUnavailableError
from src.utils.exceptions.live_chat import (
    ChatAlreadyAssignedError, ChatNotFoundError, ExecutiveChatLimitError, NotChatOwnerError)

router = APIRouter(tags=["Chat en vivo"])
logger = logging.getLogger(__name__)

HubDep = Annotated[ConnectionHub, Depends(get_hub)]
ClockDep = Annotated[Clock, Depends(get_clock)]

@router.get("/api/v1/live-chats", responses={401: {}, 503: {}})
async def waiting_chats(executive: CurrentExecutive, session: SessionDep, status: Literal["waiting"] = "waiting") -> list[WaitingChat]:
    try:
        chats = await list_waiting(session)
    except DatabaseUnavailableError as exc:
        logger.error("Cola web: base de datos no disponible (%s)", exc)
        raise HTTPException(503, "Servicio no disponible") from exc
    return [WaitingChat(id=chat.id, customer_name=chat.customer_name, created_at=chat.created_at) for chat in chats]

@router.post("/api/v1/live-chats/{chat_id}/take", responses={401: {}, 404: {}, 409: {}, 503: {}})
async def take_chat(chat_id: int, executive: CurrentExecutive, session: SessionDep, hub: HubDep, clock: ClockDep) -> ChatSummary:
    try:
        logger.debug("El ejecutivo %s toma el chat %s", executive.id, chat_id)
        max_chats = await get_int_property(session, "executive_max_chats", 3)
        chat = await take(session, chat_id, executive.id, max_chats, clock.now())
        await hub.publish(session, Event("chat_taken", chat.id, web_session_id=str(chat.web_session_id), executive_id=executive.id))
        await commit(session)
        return ChatSummary.from_chat(chat)
    except ChatNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat no encontrado") from exc
    except ChatAlreadyAssignedError as exc:
        logger.warning("El chat %s ya estaba asignado", chat_id)
        raise HTTPException(status.HTTP_409_CONFLICT, "El chat ya fue asignado a otro ejecutivo") from exc
    except ExecutiveChatLimitError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Alcanzaste el máximo de chats simultáneos") from exc
    except DatabaseUnavailableError as exc:
        logger.error("Tomar chat: base de datos no disponible (%s)", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Servicio no disponible") from exc

@router.post("/api/v1/live-chats/{chat_id}/close", status_code=status.HTTP_204_NO_CONTENT,
             responses={401: {}, 403: {}, 404: {}, 503: {}})
async def close_chat(chat_id: int, executive: CurrentExecutive, session: SessionDep, hub: HubDep, clock: ClockDep) -> None:
    try:
        chat = await close(session, chat_id, executive.id, clock.now())
        await hub.publish(session, Event("chat_closed", chat.id, web_session_id=str(chat.web_session_id),
                                         executive_id=executive.id, reason="executive"))
        await commit(session)
    except NotChatOwnerError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo el ejecutivo asignado puede cerrar el chat") from exc
    except ChatNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat no encontrado") from exc
    except DatabaseUnavailableError as exc:
        logger.error("Cerrar chat: base de datos no disponible (%s)", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Servicio no disponible") from exc
