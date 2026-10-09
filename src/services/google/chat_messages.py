"""Mensajes que el asistente publica por su cuenta en Google Chat, como el enlace del EDR (spec 003, RF-11, RF-14),
con la cuenta de servicio de la app y el scope chat.bot."""
from typing import Any
import httpx
from src.services.google.chat_media import CHAT_API_URL
from src.services.google.service_account import CHAT_SCOPE, service_account_token

THREAD_SEPARATOR = "/threads/"

def message_target(chat_key: str) -> tuple[str, dict[str, Any], dict[str, str]]:
    """Space, cuerpo y parámetros a partir de conversation.external_key: un hilo (spaces/X/threads/Y) en un space o el
    space completo en un mensaje directo (plan 003, D7)."""
    if THREAD_SEPARATOR not in chat_key:
        return chat_key, {}, {}
    space = chat_key.split(THREAD_SEPARATOR, 1)[0]
    return space, {"thread": {"name": chat_key}}, {"messageReplyOption": "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"}

class ChatMessenger:
    def __init__(self, http: httpx.AsyncClient, service_account: dict[str, Any]):
        self._http = http
        self._service_account = service_account

    async def post(self, chat_key: str, text: str) -> None:
        space, thread, params = message_target(chat_key)
        token = await service_account_token(self._http, self._service_account, CHAT_SCOPE)
        response = await self._http.post(f"{CHAT_API_URL}/{space}/messages", json={"text": text, **thread},
                                         params=params, headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
