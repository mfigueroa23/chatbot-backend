import httpx
import pytest
from fastapi.testclient import TestClient
from main import app
from src.interfaces.google_chat import AddonEvent
from src.services import google_chat
from src.services.attachments import Attachment
from src.services.google_chat import (
    CHAT_SCOPE, attachments_of, conversation_key, download, message_text, service_account_token, verify_addon_token)
from src.utils.exceptions.attachments import AttachmentTooLargeError
from src.utils.exceptions.google_chat import InvalidGoogleTokenError

AUDIENCE = "https://chatbot.example/api/v1/google-chat/events"
ACCOUNT = "service-1@gcp-sa-gsuiteaddons.iam.gserviceaccount.com"
TOKEN_URI = "https://oauth2.googleapis.com/token"
VALID = {"iss": "https://accounts.google.com", "email": ACCOUNT, "email_verified": True}


def space_event() -> dict:
    return {"chat": {"messagePayload": {
        "space": {"name": "spaces/AAA", "spaceType": "SPACE"},
        "message": {"text": "@Asistente ¿cómo pago?", "argumentText": " ¿cómo pago?",
                    "thread": {"name": "spaces/AAA/threads/T1"}}}}}


def dm_event() -> dict:
    return {"chat": {"messagePayload": {
        "space": {"name": "spaces/DM1", "spaceType": "DIRECT_MESSAGE"},
        "message": {"text": "¿cómo pago?", "thread": {"name": "spaces/DM1/threads/X9"}}}}}


@pytest.fixture
def claims(monkeypatch):
    """Simula la decodificación del ID token: los tests no descargan certificados de Google."""
    decoded = dict(VALID)

    async def certs(http):
        return {"kid": "cert"}

    def decode(token, certs, audience):
        if audience != AUDIENCE:
            raise ValueError("audiencia incorrecta")
        return decoded

    monkeypatch.setattr(google_chat, "get_google_certs", certs)
    monkeypatch.setattr(google_chat.jwt, "decode", decode)
    return decoded


async def verify(token: str | None) -> None:
    async with httpx.AsyncClient() as http:
        await verify_addon_token(token, AUDIENCE, ACCOUNT, http)


@pytest.mark.anyio
async def test_token_valido_de_la_cuenta_del_complemento(claims):
    await verify("token")


@pytest.mark.anyio
@pytest.mark.parametrize("token, change", [
    (None, {}),
    ("token", {"iss": "https://evil.example"}),
    ("token", {"email": "otra@gcp-sa-gsuiteaddons.iam.gserviceaccount.com"}),
    ("token", {"email_verified": False}),
])
async def test_token_invalido_lanza_error(claims, token, change):
    claims.update(change)

    with pytest.raises(InvalidGoogleTokenError):
        await verify(token)


def test_key_es_el_hilo_en_un_space_y_el_space_en_un_dm():
    assert conversation_key(AddonEvent.model_validate(space_event())) == "spaces/AAA/threads/T1"
    assert conversation_key(AddonEvent.model_validate(dm_event())) == "spaces/DM1"


def test_text_usa_argument_text_en_un_space_y_el_texto_en_un_dm():
    assert message_text(AddonEvent.model_validate(space_event())) == "¿cómo pago?"
    assert message_text(AddonEvent.model_validate(dm_event())) == "¿cómo pago?"


def test_sender_se_lee_del_evento():
    payload = space_event()
    payload["chat"]["messagePayload"]["message"]["sender"] = {"name": "users/123", "type": "HUMAN"}

    message = AddonEvent.model_validate(payload).chat.message_payload.message  # pyright: ignore[reportOptionalMemberAccess] -- el evento de prueba siempre trae chat y messagePayload

    assert message is not None
    assert message.sender is not None
    assert message.sender.name == "users/123"


def test_sender_es_none_si_el_evento_no_lo_trae():
    message = AddonEvent.model_validate(space_event()).chat.message_payload.message  # pyright: ignore[reportOptionalMemberAccess] -- el evento de prueba siempre trae chat y messagePayload

    assert message is not None
    assert message.sender is None


def test_endpoint_sin_token_responde_401_antes_de_leer_la_configuracion():
    response = TestClient(app).post("/api/v1/google-chat/events", json=space_event())

    assert response.status_code == 401


def test_attachments_solo_descarga_los_archivos_subidos_al_chat():
    event = dm_event()
    event["chat"]["messagePayload"]["message"]["attachment"] = [
        {"contentName": "contrato.pdf", "contentType": "application/pdf", "source": "UPLOADED_CONTENT",
         "attachmentDataRef": {"resourceName": "spaces/DM1/attachments/A1"}},
        {"contentName": "informe.docx", "contentType": "application/octet-stream", "source": "DRIVE_FILE",
         "driveDataRef": {"driveFileId": "D1"}}]

    assert attachments_of(AddonEvent.model_validate(event)) == [
        Attachment("contrato.pdf", "application/pdf", "spaces/DM1/attachments/A1"),
        Attachment("informe.docx", "application/octet-stream", None)]
    assert attachments_of(AddonEvent.model_validate(space_event())) == []


def mock_http(content: bytes, seen: list[httpx.Request]) -> httpx.AsyncClient:
    """Cliente con un transporte falso: los tests no llaman a Google."""
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if str(request.url) == TOKEN_URI:
            return httpx.Response(200, json={"access_token": "ya29.token"})
        return httpx.Response(200, content=content)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_token_de_la_cuenta_de_servicio_con_scope_chat_bot(monkeypatch):
    class FakeSigner:
        key_id = None

        def sign(self, message):
            return b"firma"

    monkeypatch.setattr(google_chat.crypt.RSASigner, "from_service_account_info", lambda info: FakeSigner())
    seen: list[httpx.Request] = []
    async with mock_http(b"", seen) as http:
        token = await service_account_token({"client_email": "bot@proyecto.iam.gserviceaccount.com",
                                             "private_key": "clave", "token_uri": TOKEN_URI}, http)

    form = dict(item.split("=", 1) for item in seen[0].content.decode().split("&"))
    claims = google_chat.jwt.decode(form["assertion"], verify=False)
    assert token == "ya29.token" and claims["scope"] == CHAT_SCOPE and claims["aud"] == TOKEN_URI
    assert claims["iss"] == "bot@proyecto.iam.gserviceaccount.com"


@pytest.mark.anyio
async def test_download_con_el_token_y_corta_al_pasar_el_maximo(monkeypatch):
    monkeypatch.setattr(google_chat, "MAX_BYTES", 1000)
    seen: list[httpx.Request] = []
    async with mock_http(b"x" * 1000, seen) as http:
        data = await download("spaces/A/attachments/1", "ya29.token", http)
    async with mock_http(b"x" * 1001, []) as http:
        with pytest.raises(AttachmentTooLargeError):
            await download("spaces/A/attachments/1", "ya29.token", http)

    assert data == b"x" * 1000
    assert seen[0].url.path == "/v1/media/spaces/A/attachments/1" and seen[0].url.params["alt"] == "media"
    assert seen[0].headers["Authorization"] == "Bearer ya29.token"
