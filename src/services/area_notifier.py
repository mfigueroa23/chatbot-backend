import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
import httpx
from google.auth import exceptions as google_exceptions
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.google_chat import build_chat_api_client
from src.utils.exceptions.database import DatabaseUnavailableError
from src.utils.exceptions.notification import NotificationDeliveryError
from src.utils.exceptions.property import PropertyNotFoundError

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_SECONDS = 10
CHANNEL_LABELS = {"web": "chat web", "google_chat": "Google Chat"}

@dataclass(frozen=True)
class Requester:
    """Quién pide algo: la identidad sale del canal, nunca del modelo."""
    name: str | None
    contact: str | None
    channel: Literal["web", "google_chat"]

class AreaNotifier:
    def __init__(self, session_factory: Callable[[], AsyncSession], transport: httpx.AsyncBaseTransport | None = None):
        self._session_factory = session_factory
        self._transport = transport

    async def notify(self, space: str, text: str) -> None:
        # El texto lleva datos del usuario: nunca se registra en el log.
        try:
            async with self._session_factory() as session, \
                    httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS, transport=self._transport) as http:
                client = await build_chat_api_client(session, http)
                await client.create_message(space, text)
        except (httpx.HTTPError, PropertyNotFoundError, DatabaseUnavailableError, ValueError, KeyError,
                google_exceptions.GoogleAuthError) as exc:
            logger.error("No se pudo notificar al space %s: %s", space, type(exc).__name__)
            raise NotificationDeliveryError(space) from exc
        logger.info("Notificación entregada al space %s", space)

def requester_line(requester: Requester) -> str:
    if requester.channel == "google_chat":
        return f"{requester.name} <{requester.contact}>"
    return f"{requester.name} · {requester.contact}"

def format_request(procedure_name: str, data: list[tuple[str, str]], requester: Requester, message: str) -> str:
    lines = [
        f"Nueva solicitud: {procedure_name}",
        f"Canal: {CHANNEL_LABELS[requester.channel]}",
        f"Solicitante: {requester_line(requester)}",
        "Datos:",
        *(f"- {label}: {value}" for label, value in data),
        f"Mensaje original: {message}",
    ]
    return "\n".join(lines)

def format_unanswered(question: str, area_name: str | None, requester: Requester) -> str:
    return "\n".join([
        "Consulta sin respuesta del asistente",
        f"Área: {area_name or 'sin área'}",
        f"Colaborador: {requester_line(requester)}",
        f"Consulta: {question}",
    ])
