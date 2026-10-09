import logging
from typing import Annotated, Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from src.interfaces.google_chat import AddonEvent, chat_reply
from src.models.conversation import Channel
from src.routers.dependencies import AssistantDepsDep, TokenVerifierDep
from src.services.assistant import answer, welcome
from src.services.google.chat_events import (attachments_of, conversation_key, message_text, requester_name_of,
                                             requester_of)
from src.utils.exceptions.database import DatabaseUnavailableError
from src.utils.exceptions.google_chat import InvalidGoogleTokenError
from src.utils.exceptions.property import PropertyNotFoundError

router = APIRouter(prefix="/api/v1", tags=["Google Chat"])
logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)

@router.post("/google-chat/events", responses={401: {"description": "Token de Google no válido"},
                                                503: {"description": "Base de datos o configuración no disponible"}})
async def google_chat_events(
    event: AddonEvent,
    deps: AssistantDepsDep,
    verify: TokenVerifierDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> dict[str, Any]:
    logger.debug("Evento de Google Chat recibido")
    try:
        await verify(credentials.credentials if credentials else None)
        chat = event.chat
        if chat is not None and chat.added_to_space_payload is not None:
            return chat_reply(await welcome(deps))
        if chat is None or chat.message_payload is None:
            return {}
        result = await answer(deps, Channel.google_chat, conversation_key(event), message_text(event),
                              requester=requester_of(event), attachments=attachments_of(event),
                              requester_name=requester_name_of(event))
    except InvalidGoogleTokenError as exc:
        logger.warning("Petición de Google Chat rechazada: %s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token de Google Chat no válido") from exc
    except PropertyNotFoundError as exc:
        logger.error("Google Chat: falta configurar la property %s", exc.key)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Servicio no disponible") from exc
    except DatabaseUnavailableError as exc:
        logger.error("Google Chat: base de datos no disponible (%s)", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Servicio no disponible") from exc
    return chat_reply(result.reply)
