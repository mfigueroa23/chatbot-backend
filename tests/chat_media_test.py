import base64
import json
import logging
import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from src.services.files.attachments import Attachment
from src.services.google.chat_media import ChatMediaClient, read_chat_attachments
from src.services.google.service_account import CHAT_SCOPE
from src.services.property import Properties
from src.utils.exceptions.attachment import AttachmentTooLargeError
from tests.fakes import FakeTranscriber

TOKEN_URI = "https://oauth2.googleapis.com/token"


def service_account() -> dict[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    return {"type": "service_account", "client_email": "bot@proyecto.iam.gserviceaccount.com",
            "private_key": pem, "private_key_id": "k1", "token_uri": TOKEN_URI}


SERVICE_ACCOUNT = service_account()


def jwt_claims(assertion: str) -> dict:
    payload = assertion.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def transport(media: bytes, seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if str(request.url) == TOKEN_URI:
            return httpx.Response(200, json={"access_token": "ya29.token"})
        return httpx.Response(200, content=media)
    return httpx.MockTransport(handler)


@pytest.mark.anyio
async def test_descarga_completa_con_token_de_scope_chat_bot():
    seen: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=transport(b"pdf-bytes", seen)) as http:
        data = await ChatMediaClient(http, SERVICE_ACCOUNT).download("spaces/A/attachments/1", 1000)

    form = dict(item.split("=", 1) for item in seen[0].content.decode().split("&"))
    assert data == b"pdf-bytes" and jwt_claims(form["assertion"])["scope"] == CHAT_SCOPE
    assert seen[1].url.path == "/v1/media/spaces/A/attachments/1" and seen[1].url.params["alt"] == "media"
    assert seen[1].headers["Authorization"] == "Bearer ya29.token"


@pytest.mark.anyio
async def test_corta_la_descarga_al_pasar_el_tope():
    async with httpx.AsyncClient(transport=transport(b"x" * 5000, [])) as http:
        with pytest.raises(AttachmentTooLargeError):
            await ChatMediaClient(http, SERVICE_ACCOUNT).download("spaces/A/attachments/1", 1000)


@pytest.mark.anyio
async def test_sin_cuenta_de_servicio_cada_archivo_queda_como_no_leido_sin_registrar_secretos(caplog):
    items = [Attachment("foto.png", "image/png", "r/1"), Attachment("doc.txt", "text/plain", "r/2")]

    with caplog.at_level(logging.DEBUG, logger="src"):
        missing = await read_chat_attachments(items, Properties({}), FakeTranscriber())
        broken = await read_chat_attachments(items, Properties({"google_chat_service_account_json": "{no es json"}),
                                             FakeTranscriber())

    assert [item.status for item in missing + broken] == ["failed"] * 4
    assert "cuenta de servicio" in caplog.text and "no es json" not in caplog.text
