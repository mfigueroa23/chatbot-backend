import asyncio
import logging
from typing import Annotated, Any
import httpx
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from src.database.session import SessionDep
from src.interfaces.google_chat import AddonEvent, chat_reply
from src.services.assistant import ask
from src.services.google_chat import (
  attachments_of, conversation_key, message_text, verify_addon_token
)
from src.services.google_chat_reply import AUDIENCIA, COORDINADOR, DEMORA, NO_DISPONIBLE, SIN_TEXTO, read_files
from src.services.property import get_property
from src.utils.exceptions.agents import AgentNotFoundError
from src.utils.exceptions.database import DatabaseUnavailableError
from src.utils.exceptions.google_chat import InvalidGoogleTokenError
from src.utils.exceptions.property import PropertyNotFoundError

router = APIRouter(prefix="/api/v1", tags=["Google Chat"])
logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)

async def verify_token(session: AsyncSession, credentials: HTTPAuthorizationCredentials | None) -> None:
  # Sin token se rechaza antes de leer la configuración.
  if credentials is None:
    raise InvalidGoogleTokenError("Falta el token Bearer")
  # Sin caché: un cambio en las properties se aplica desde el siguiente evento.
  audience = await get_property(session, "google_chat_audience")
  service_account = await get_property(session, "google_chat_addon_service_account")
  async with httpx.AsyncClient(timeout = 10) as http:
    await verify_addon_token(credentials.credentials, audience, service_account, http)

@router.post("/google-chat/events", responses={ 401: { "description": "Token de Google no válido" } })
async def google_chat_events(
  request: Request,
  event: AddonEvent,
  session: SessionDep,
  credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> dict[str, Any]:
  tiempo_maximo: int | None = None
  try:
    await verify_token(session, credentials)
    if event.chat is not None and event.chat.added_to_space_payload is not None:
      return chat_reply(await get_property(session, "google_chat_welcome"))
    # El hilo sale del evento firmado por Google, nunca del texto del usuario.
    thread_id = conversation_key(event)
    mensaje = message_text(event)
    adjuntos = attachments_of(event)
    if not thread_id or not (mensaje or adjuntos):
      return {}
    tiempo_maximo = int(await get_property(session, "google_timeout"))
    async with asyncio.timeout(tiempo_maximo):
      # El texto de los archivos se suma al mensaje y queda en el historial como texto.
      if adjuntos:
        mensaje = f"{mensaje or SIN_TEXTO}\n\n{await read_files(session, adjuntos)}"
      return chat_reply(await ask(request.app.state.graph, session, COORDINADOR, AUDIENCIA, thread_id, mensaje))
  except InvalidGoogleTokenError as exc:
    logger.warning("Evento de Google Chat rechazado: %s", exc)
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token de Google no válido") from exc
  # Google Chat solo muestra la respuesta si es 200, por eso los errores se responden como mensaje.
  except TimeoutError:
    logger.warning("Se superaron los %s segundos para responder en Google Chat", tiempo_maximo)
    return chat_reply(DEMORA)
  except (PropertyNotFoundError, AgentNotFoundError) as exc:
    logger.error("Agente mal configurado: %s", exc)
    return chat_reply(NO_DISPONIBLE)
  except (DatabaseUnavailableError, psycopg.OperationalError) as exc:
    logger.error("Base de datos no disponible: %s", exc)
    return chat_reply(NO_DISPONIBLE)
  except Exception:
    logger.exception("Ha ocurrido un error al responder en Google Chat")
    return chat_reply(NO_DISPONIBLE)
