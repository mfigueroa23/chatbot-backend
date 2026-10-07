import json
import re
import time
from typing import Any
import httpx
from google.auth import crypt, exceptions, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from src.interfaces.google_chat import ChatEvent
from src.models.business_area import AreaScope
from src.services.business_data import get_areas
from src.services.chat_orchestrator import handle_internal_message
from src.services.property import get_str_property
from src.utils.exceptions.google_chat import InvalidGoogleTokenError

CHAT_ISSUER = "chat@system.gserviceaccount.com"
CHAT_CERTS_URL = f"https://www.googleapis.com/service_accounts/v1/metadata/x509/{CHAT_ISSUER}"
CHAT_API_URL = "https://chat.googleapis.com/v1"
CHAT_SCOPE = "https://www.googleapis.com/auth/chat.bot"

_certs: dict[str, str] = {}
_certs_expire_at = 0.0

async def get_chat_certs(http: httpx.AsyncClient) -> dict[str, str]:
    global _certs, _certs_expire_at
    if time.monotonic() >= _certs_expire_at:
        response = await http.get(CHAT_CERTS_URL)
        response.raise_for_status()
        _certs = response.json()
        # Google rota los certificados: se respeta el max-age que indica la respuesta.
        max_age = re.search(r"max-age=(\d+)", response.headers.get("Cache-Control", ""))
        _certs_expire_at = time.monotonic() + (int(max_age.group(1)) if max_age else 0)
    return _certs

async def verify_chat_token(token: str | None, audience: str, http: httpx.AsyncClient) -> None:
    if not token:
        raise InvalidGoogleTokenError("Falta el token Bearer")
    try:
        certs = await get_chat_certs(http)
        claims = jwt.decode(token, certs=certs, audience=audience)
    except (ValueError, exceptions.GoogleAuthError, httpx.HTTPError) as exc:
        raise InvalidGoogleTokenError(str(exc)) from exc
    if claims.get("iss") != CHAT_ISSUER:
        raise InvalidGoogleTokenError("El emisor del token no es Google Chat")

async def handle_event(event: ChatEvent, session: AsyncSession) -> dict[str, str]:
    if event.type == "ADDED_TO_SPACE":
        areas = await get_areas(session, AreaScope.internal)
        names = ", ".join(area.name for area in areas)
        return {"text": f"¡Hola! Soy el asistente virtual. Puedo ayudarte con dudas de: {names}."}
    if event.type != "MESSAGE" or event.message is None:
        return {}
    is_dm = event.space is not None and event.space.space_type == "DIRECT_MESSAGE"
    # En un space solo cuenta el texto que acompaña a la mención; en un mensaje directo, el texto completo.
    text = event.message.text if is_dm else event.message.argument_text
    user = event.user
    return {"text": await handle_internal_message(
        session, text or "", user.display_name if user else None, user.email if user else None)}

class ChatApiClient:
    def __init__(self, http: httpx.AsyncClient, service_account: dict[str, Any]):
        self._http = http
        self._service_account = service_account

    async def create_message(self, space: str, thread: str, text: str) -> None:
        response = await self._http.post(
            f"{CHAT_API_URL}/{space}/messages",
            params={"messageReplyOption": "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"},
            json={"text": text, "thread": {"name": thread}},
            headers={"Authorization": f"Bearer {await self._access_token()}"},
        )
        response.raise_for_status()

    async def _access_token(self) -> str:
        # OAuth de cuenta de servicio con JWT-bearer: evita google.auth.transport.requests, que es síncrono.
        signer = crypt.RSASigner.from_service_account_info(self._service_account)
        token_uri = self._service_account["token_uri"]
        now = int(time.time())
        assertion = jwt.encode(signer, {
            "iss": self._service_account["client_email"],
            "scope": CHAT_SCOPE,
            "aud": token_uri,
            "iat": now,
            "exp": now + 3600,
        })
        response = await self._http.post(token_uri, data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion.decode(),
        })
        response.raise_for_status()
        return response.json()["access_token"]

async def build_chat_api_client(session: AsyncSession, http: httpx.AsyncClient) -> ChatApiClient:
    service_account = json.loads(await get_str_property(session, "google_chat_service_account_json"))
    return ChatApiClient(http, service_account)
