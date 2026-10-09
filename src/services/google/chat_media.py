"""Descarga de adjuntos subidos a Google Chat (attachmentDataRef) con la cuenta de servicio y el scope chat.bot."""
import json
import logging
from collections.abc import Sequence
from typing import Any
import httpx
from src.agents.llm import Transcriber
from src.services.files.attachments import Attachment, AttachmentText, limits_from, read_attachments
from src.services.google.service_account import CHAT_SCOPE, service_account_token
from src.services.property import Properties
from src.utils.exceptions.attachment import AttachmentTooLargeError
from src.utils.exceptions.property import PropertyNotFoundError

logger = logging.getLogger(__name__)

CHAT_API_URL = "https://chat.googleapis.com/v1"
DOWNLOAD_TIMEOUT_SECONDS = 20

class ChatMediaClient:
    def __init__(self, http: httpx.AsyncClient, service_account: dict[str, Any]):
        self._http = http
        self._service_account = service_account

    async def download(self, resource_name: str, max_bytes: int) -> bytes:
        # Chat no informa el tamaño y admite hasta 200 MB: se corta al pasar el tope en vez de cargarlo entero
        # (spec 002, RF-37; plan D4).
        token = await service_account_token(self._http, self._service_account, CHAT_SCOPE)
        chunks: list[bytes] = []
        received = 0
        async with self._http.stream("GET", f"{CHAT_API_URL}/media/{resource_name}", params={"alt": "media"},
                                     headers={"Authorization": f"Bearer {token}"}) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                received += len(chunk)
                if received > max_bytes:
                    raise AttachmentTooLargeError(resource_name)
                chunks.append(chunk)
        return b"".join(chunks)


async def read_chat_attachments(attachments: Sequence[Attachment], properties: Properties,
                                transcriber: Transcriber) -> list[AttachmentText]:
    """Lee los adjuntos de Google Chat con la cuenta de servicio. Sin la cuenta configurada, cada archivo queda como
    «no se pudo leer» (spec 002, RF-39)."""
    limits = limits_from(properties)
    try:
        service_account = json.loads(properties.required("google_chat_service_account_json"))
    except (PropertyNotFoundError, ValueError) as exc:
        logger.error("No se pueden descargar adjuntos de Google Chat: falta o es inválida la cuenta de servicio (%s)",
                     type(exc).__name__)
        return [AttachmentText(item.name, "failed") for item in attachments]
    async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT_SECONDS) as http:
        return await read_attachments(attachments, ChatMediaClient(http, service_account), transcriber, limits)
