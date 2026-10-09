import logging
from fastapi import APIRouter, HTTPException, status
from src.interfaces.web_chat import ChatRequest, ChatResponse
from src.models.conversation import Channel
from src.routers.dependencies import AssistantDepsDep
from src.services.assistant import answer
from src.utils.exceptions.database import DatabaseUnavailableError

router = APIRouter(prefix="/api/v1", tags=["Chat web"])
logger = logging.getLogger(__name__)

@router.post("/chat", responses={503: {"description": "Base de datos no disponible"}})
async def chat(request: ChatRequest, deps: AssistantDepsDep) -> ChatResponse:
    logger.debug("Mensaje del chat web recibido")
    try:
        result = await answer(deps, Channel.web, request.session_id, request.message)
    except DatabaseUnavailableError as exc:
        logger.error("Chat web: base de datos no disponible (%s)", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Servicio no disponible") from exc
    return ChatResponse(session_id=result.conversation_id, reply=result.reply)
