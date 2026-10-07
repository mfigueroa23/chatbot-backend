import json
import time
from typing import Any
import httpx
from google.auth import crypt, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.property import get_str_property

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
