import re
import time
import httpx
from google.auth import exceptions, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from src.interfaces.google_chat import ChatEvent
from src.models.business_area import AreaScope
from src.services.business_data import get_areas
from src.services.chat_orchestrator import handle_internal_message
from src.utils.exceptions.google_chat import InvalidGoogleTokenError

CHAT_ISSUER = "chat@system.gserviceaccount.com"
CHAT_CERTS_URL = f"https://www.googleapis.com/service_accounts/v1/metadata/x509/{CHAT_ISSUER}"

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
