import logging
from fastapi import APIRouter, Response, status
from src.interfaces.chat import ChatRequest, ChatResponse

route = APIRouter(tags=['Chat'])
logger = logging.getLogger(__name__)

@route.post("/chat", responses={ 500: { "model": ChatResponse } })
def chat(response: Response, message: ChatRequest) -> ChatResponse:
  try:
    logger.debug(f"Solicitando mensaje desde el chat ID: '{message.chat_id}'")
    return ChatResponse(respuesta = message.mensaje)
  except Exception:
    logger.exception(f"Ha ocurrido un error al solicitar una respuesta {Exception.__cause__}")
    response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    return ChatResponse(respuesta = "Servicio no disponible. Intente de nuevo más tarde")
