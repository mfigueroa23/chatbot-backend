import json
import time
from typing import Any
import httpx
from google.auth import crypt, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.property import get_str_property
from src.utils.exceptions.attachment import AttachmentTooLargeError

CHAT_API_URL = "https://chat.googleapis.com/v1"
CHAT_SCOPE = "https://www.googleapis.com/auth/chat.bot"

class ChatApiClient:
    def __init__(self, http: httpx.AsyncClient, service_account: dict[str, Any]):
        self._http = http
        self._service_account = service_account

    async def create_message(self, space: str, text: str, thread: str | None = None) -> None:
        body: dict[str, Any] = {"text": text}
        params = {}
        if thread is not None:
            body["thread"] = {"name": thread}
            params["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
        response = await self._http.post(
            f"{CHAT_API_URL}/{space}/messages",
            params=params,
            json=body,
            headers={"Authorization": f"Bearer {await self._access_token()}"},
        )
        response.raise_for_status()

    async def download_media(self, resource_name: str, max_bytes: int | None = None) -> bytes:
        # Adjunto subido directamente a Chat (attachmentDataRef): se descarga con el mismo scope chat.bot. Chat no informa
        # el tamaño y admite hasta 200 MB, así que se corta al pasar el tope en vez de cargarlo entero en memoria.
        headers = {"Authorization": f"Bearer {await self._access_token()}"}
        chunks: list[bytes] = []
        received = 0
        async with self._http.stream("GET", f"{CHAT_API_URL}/media/{resource_name}", params={"alt": "media"},
                                     headers=headers) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                received += len(chunk)
                if max_bytes is not None and received > max_bytes:
                    raise AttachmentTooLargeError(resource_name)
                chunks.append(chunk)
        return b"".join(chunks)

    async def _access_token(self) -> str:
        return await service_account_token(self._http, self._service_account, CHAT_SCOPE)

async def service_account_token(http: httpx.AsyncClient, service_account: dict[str, Any], scope: str) -> str:
    # OAuth de cuenta de servicio con JWT-bearer: evita google.auth.transport.requests, que es síncrono. El scope se pide
    # por llamada para usar la misma cuenta de servicio con Chat y con Drive.
    signer = crypt.RSASigner.from_service_account_info(service_account)
    token_uri = service_account["token_uri"]
    now = int(time.time())
    assertion = jwt.encode(signer, {
        "iss": service_account["client_email"],
        "scope": scope,
        "aud": token_uri,
        "iat": now,
        "exp": now + 3600,
    })
    response = await http.post(token_uri, data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion.decode(),
    })
    response.raise_for_status()
    return response.json()["access_token"]

async def build_chat_api_client(session: AsyncSession, http: httpx.AsyncClient) -> ChatApiClient:
    service_account = json.loads(await get_str_property(session, "google_chat_service_account_json"))
    return ChatApiClient(http, service_account)
