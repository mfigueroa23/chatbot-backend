"""Token OAuth de la cuenta de servicio (google_chat_service_account_json) con JWT-bearer: evita
google.auth.transport.requests, que es síncrono. La credencial nunca va al log (spec 002, RNF-8)."""
import time
from typing import Any
import httpx
from google.auth import crypt, jwt

CHAT_SCOPE = "https://www.googleapis.com/auth/chat.bot"

async def service_account_token(http: httpx.AsyncClient, service_account: dict[str, Any], scope: str) -> str:
    signer = crypt.RSASigner.from_service_account_info(service_account)
    token_uri = service_account["token_uri"]
    now = int(time.time())
    assertion = jwt.encode(signer, {
        "iss": service_account["client_email"], "scope": scope, "aud": token_uri, "iat": now, "exp": now + 3600})
    response = await http.post(token_uri, data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion.decode()})
    response.raise_for_status()
    return response.json()["access_token"]
