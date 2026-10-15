import asyncio
import logging
import httpx
import psycopg
from langgraph.graph import MessagesState
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.context import CoordinatorContext
from src.agents.llm import LLM
from src.database.session import SessionLocal
from src.interfaces.google_chat import AddonEvent
from src.services.assistant import ask
from src.services.attachments import Attachment, read_attachments
from src.services.google_chat import attachments_of, chat_token, conversation_key, download, message_text
from src.services.property import get_property
from src.utils.exceptions.agents import AgentNotFoundError
from src.utils.exceptions.database import DatabaseUnavailableError
from src.utils.exceptions.property import PropertyNotFoundError

logger = logging.getLogger(__name__)

AUDIENCIA = "interno"
COORDINADOR = "Agente Interno"
NO_DISPONIBLE = "Servicio no disponible. Intenta de nuevo más tarde"
DEMORA = "Me tomó demasiado tiempo revisar tu mensaje. Intenta de nuevo, por ejemplo con un archivo más pequeño"
SIN_TEXTO = "Revisa el archivo adjunto"
AVISO = "Estoy revisando tu solicitud. Te enviaré la respuesta en un mensaje nuevo cuando esté lista"
AVISO_POR_DEFECTO = 10.0

async def read_thresholds(session: AsyncSession) -> tuple[float, float]:
  # Sin caché: un cambio en las properties se aplica desde el siguiente evento.
  try:
    notice = float(await get_property(session, "google_chat_notice_seconds"))
  except PropertyNotFoundError:
    # Desplegar sin cargar el aviso no rompe el endpoint.
    notice = AVISO_POR_DEFECTO
  # google_timeout es el tiempo máximo total; si falta, la configuración está incompleta.
  maximum = float(await get_property(session, "google_timeout"))
  return notice, maximum

async def read_files(session: AsyncSession, adjuntos: list[Attachment]) -> str:
  llm = await LLM.create(session)
  async with httpx.AsyncClient(timeout = 20) as http:
    # Sin la cuenta de servicio los archivos quedan como "no se pudo leer" y se responde igual el texto.
    token = await chat_token(session, http)

    async def download_file(resource_name: str) -> bytes:
      if token is None:
        raise RuntimeError("Falta el token de la cuenta de servicio de Google Chat")
      return await download(resource_name, token, http)

    return await read_attachments(adjuntos, download_file, llm.llm)

async def process(graph: CompiledStateGraph[MessagesState, CoordinatorContext], event: AddonEvent, maximum: float) -> str:
  # Devuelve siempre un texto (respuesta o mensaje de error) para que la vía síncrona y la diferida lo entreguen igual.
  # El hilo sale del evento firmado por Google, nunca del texto del usuario.
  thread_id = conversation_key(event)
  mensaje = message_text(event)
  adjuntos = attachments_of(event)
  try:
    # Sesión propia: la de la petición se cierra al responder el aviso.
    async with SessionLocal() as session, asyncio.timeout(maximum):
      # El texto de los archivos se suma al mensaje y queda en el historial como texto.
      if adjuntos:
        mensaje = f"{mensaje or SIN_TEXTO}\n\n{await read_files(session, adjuntos)}"
      return await ask(graph, session, COORDINADOR, AUDIENCIA, thread_id, mensaje)
  except TimeoutError:
    logger.warning("Se superaron los %s segundos para responder en Google Chat", maximum)
    return DEMORA
  except (PropertyNotFoundError, AgentNotFoundError) as exc:
    logger.error("Agente mal configurado: %s", exc)
    return NO_DISPONIBLE
  except (DatabaseUnavailableError, psycopg.OperationalError) as exc:
    logger.error("Base de datos no disponible: %s", exc)
    return NO_DISPONIBLE
  except Exception:
    logger.exception("Ha ocurrido un error al responder en Google Chat")
    return NO_DISPONIBLE
