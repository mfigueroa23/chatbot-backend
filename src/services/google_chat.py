import re
import time
import httpx
from google.auth import exceptions, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.graph import AgentGraph
from src.interfaces.google_chat import AddonEvent
from src.services.area_notifier import Requester
from src.services.attachments import Attachment
from src.services.chat_orchestrator import handle_internal_message
from src.utils.exceptions.google_chat import InvalidGoogleTokenError

# Los complementos de Google Workspace firman sus peticiones con un ID token de Google.
GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v1/certs"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
# Al añadir el bot a un space no hay mensaje del usuario: el coordinador saluda a partir de esta nota.
ADDED_TO_SPACE_NOTE = "[Nota del sistema: te acaban de añadir a este espacio de Google Chat. Saluda y cuenta en qué puedes ayudar.]"

_certs: dict[str, str] = {}
_certs_expire_at = 0.0

async def get_google_certs(http: httpx.AsyncClient) -> dict[str, str]:
    global _certs, _certs_expire_at
    if time.monotonic() >= _certs_expire_at:
        response = await http.get(GOOGLE_CERTS_URL)
        response.raise_for_status()
        _certs = response.json()
        # Google rota los certificados: se respeta el max-age que indica la respuesta.
        max_age = re.search(r"max-age=(\d+)", response.headers.get("Cache-Control", ""))
        _certs_expire_at = time.monotonic() + (int(max_age.group(1)) if max_age else 0)
    return _certs

async def verify_addon_token(token: str | None, audience: str, service_account: str, http: httpx.AsyncClient) -> None:
    if not token:
        raise InvalidGoogleTokenError("Falta el token Bearer")
    try:
        certs = await get_google_certs(http)
        claims = jwt.decode(token, certs=certs, audience=audience)
    except (ValueError, exceptions.GoogleAuthError, httpx.HTTPError) as exc:
        raise InvalidGoogleTokenError(str(exc)) from exc
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise InvalidGoogleTokenError("El emisor del token no es Google")
    # Solo la cuenta de servicio de este complemento: un ID token de Google de otra cuenta no basta.
    if claims.get("email") != service_account or claims.get("email_verified") is not True:
        raise InvalidGoogleTokenError("El token no es de la cuenta de servicio del complemento")

def conversation_id(event: AddonEvent) -> str:
    # En un mensaje directo cada mensaje trae un hilo nuevo: la conversación es el space. En un space de grupo, el hilo.
    payload = event.chat.message_payload if event.chat else None
    space = payload.space if payload else None
    if space is not None and space.space_type == "DIRECT_MESSAGE":
        return space.name
    thread = payload.message.thread if payload and payload.message else None
    return thread.name if thread else (space.name if space else "")

async def handle_event(event: AddonEvent, session: AsyncSession, graph: AgentGraph) -> str | None:
    chat = event.chat
    if chat is None:
        return None
    user = chat.user
    requester = Requester(user.display_name if user else None, user.email if user else None, "google_chat")
    if chat.added_to_space_payload is not None:
        space = chat.added_to_space_payload.space
        return await handle_internal_message(session, graph, ADDED_TO_SPACE_NOTE, requester, space.name if space else "")
    payload = chat.message_payload
    if payload is None or payload.message is None:
        return None
    is_dm = payload.space is not None and payload.space.space_type == "DIRECT_MESSAGE"
    # En un space solo cuenta el texto que acompaña a la mención; en un mensaje directo, el texto completo.
    text = payload.message.text if is_dm else payload.message.argument_text
    attachments = [
        Attachment(item.content_name, item.content_type,
                   resource_name=item.attachment_data_ref.resource_name if item.attachment_data_ref else None,
                   drive_file_id=item.drive_data_ref.drive_file_id if item.drive_data_ref else None)
        for item in payload.message.attachment]
    return await handle_internal_message(session, graph, text or "", requester, conversation_id(event), attachments=attachments)
