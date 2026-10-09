import json
import httpx
import pytest
from src.services.google.chat_messages import ChatMessenger, message_target
from src.services.google.drive import DRIVE_SCOPE, DriveClient
from src.services.google.service_account import CHAT_SCOPE
from tests.chat_media_test import SERVICE_ACCOUNT, TOKEN_URI, jwt_claims


def google(seen: list[httpx.Request], status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if str(request.url) == TOKEN_URI:
            return httpx.Response(200, json={"access_token": "ya29.token"})
        return httpx.Response(status, json={"id": "doc-1", "webViewLink": "https://docs.google.com/document/d/doc-1"})
    return httpx.MockTransport(handler)


def scope_of(request: httpx.Request) -> str:
    form = dict(item.split("=", 1) for item in request.content.decode().split("&"))
    return jwt_claims(form["assertion"])["scope"]


@pytest.mark.anyio
async def test_crea_el_google_doc_desde_html_en_la_carpeta():
    seen: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=google(seen)) as http:
        upload = await DriveClient(http, SERVICE_ACCOUNT).create_document_from_html("EDR PoC", "carpeta-1", "<h1>á</h1>")

    request = seen[1]
    body = request.content.decode()
    assert upload.id == "doc-1" and upload.web_link.endswith("doc-1") and scope_of(seen[0]) == DRIVE_SCOPE
    assert request.method == "POST" and request.url.params["uploadType"] == "multipart"
    assert request.url.params["supportsAllDrives"] == "true"
    assert '"parents": ["carpeta-1"]' in body and "application/vnd.google-apps.document" in body and "<h1>á</h1>" in body


@pytest.mark.anyio
async def test_reemplaza_el_mismo_documento():
    seen: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=google(seen)) as http:
        await DriveClient(http, SERVICE_ACCOUNT).replace_document_html("doc-1", "<p>v2</p>")

    assert seen[1].method == "PATCH" and seen[1].url.path.endswith("/files/doc-1") and seen[1].content == b"<p>v2</p>"


@pytest.mark.anyio
async def test_drive_con_error_lanza_la_excepcion():
    async with httpx.AsyncClient(transport=google([], status=403)) as http:
        with pytest.raises(httpx.HTTPStatusError):
            await DriveClient(http, SERVICE_ACCOUNT).replace_document_html("doc-1", "<p></p>")


def test_el_destino_es_el_hilo_en_un_space_o_el_dm():
    assert message_target("spaces/AAA/threads/T1") == (
        "spaces/AAA", {"thread": {"name": "spaces/AAA/threads/T1"}},
        {"messageReplyOption": "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"})
    assert message_target("spaces/DM1") == ("spaces/DM1", {}, {})


@pytest.mark.anyio
async def test_publica_el_mensaje_en_el_hilo_con_scope_chat_bot():
    seen: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=google(seen)) as http:
        await ChatMessenger(http, SERVICE_ACCOUNT).post("spaces/AAA/threads/T1", "Listo")

    request = seen[1]
    assert scope_of(seen[0]) == CHAT_SCOPE and request.url.path == "/v1/spaces/AAA/messages"
    assert json.loads(request.content) == {"text": "Listo", "thread": {"name": "spaces/AAA/threads/T1"}}
