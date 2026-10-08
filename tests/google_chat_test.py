import json
import time
from datetime import UTC, datetime, timedelta
from typing import cast
import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from google.auth import crypt, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from main import app
from src.agents.graph import AgentGraph
from src.database.session import get_session_factory
from src.interfaces.google_chat import AddonEvent, chat_reply
from src.routers import google_chat as google_chat_router
from src.services import google_chat
from src.services.area_notifier import Requester
from src.services.chat_api_client import ChatApiClient
from src.services.google_chat import handle_event, verify_addon_token
from src.utils.exceptions.google_chat import InvalidGoogleTokenError
from tests.fakes import property_session, service_account_info

AUDIENCE = "https://chatbot.autofin.cl/api/v1/google-chat/events"
ADDON_ACCOUNT = "service-123456@gcp-sa-gsuiteaddons.iam.gserviceaccount.com"
SESSION = cast(AsyncSession, object())
GRAPH = cast(AgentGraph, object())


def private_key_pem(key: rsa.RSAPrivateKey) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()


def certificate_pem(key: rsa.RSAPrivateKey) -> str:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(1).not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.PEM).decode()


GOOGLE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def id_token(audience: str = AUDIENCE, email: str = ADDON_ACCOUNT, email_verified: bool = True,
             key: rsa.RSAPrivateKey = GOOGLE_KEY, issuer: str = "https://accounts.google.com") -> str:
    signer = crypt.RSASigner.from_string(private_key_pem(key), key_id="kid-1")
    now = int(time.time())
    claims = {"iss": issuer, "aud": audience, "email": email, "email_verified": email_verified, "iat": now, "exp": now + 300}
    return jwt.encode(signer, claims).decode()


def certs_client() -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/oauth2/v1/certs"
        return httpx.Response(200, json={"kid-1": certificate_pem(GOOGLE_KEY)}, headers={"Cache-Control": "public, max-age=3600"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def reset_certs_cache():
    google_chat._certs_expire_at = 0.0


# --- ID token del complemento -------------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_token_valido_se_acepta():
    async with certs_client() as http:
        await verify_addon_token(id_token(), AUDIENCE, ADDON_ACCOUNT, http)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "token",
    [None, id_token(key=OTHER_KEY), id_token(audience="https://otra.app"), id_token(email="otra@gcp-sa-gsuiteaddons.iam.gserviceaccount.com"),
     id_token(email_verified=False), id_token(issuer="https://evil.example.com")],
    ids=["ausente", "firma_invalida", "audiencia_distinta", "otra_cuenta", "email_sin_verificar", "otro_emisor"],
)
async def test_token_invalido_se_rechaza(token: str | None):
    async with certs_client() as http:
        with pytest.raises(InvalidGoogleTokenError):
            await verify_addon_token(token, AUDIENCE, ADDON_ACCOUNT, http)


# --- Eventos del complemento --------------------------------------------------------------------------------------

def message_event(text: str, argument_text: str | None = None, space_type: str = "DIRECT_MESSAGE") -> AddonEvent:
    return AddonEvent.model_validate({
        "commonEventObject": {"hostApp": "CHAT"},
        "chat": {
            "user": {"name": "users/1", "email": "ana@autofin.cl", "displayName": "Ana Pérez"},
            "messagePayload": {
                "space": {"name": "spaces/AAA", "spaceType": space_type},
                "message": {"text": text, "argumentText": argument_text, "thread": {"name": "spaces/AAA/threads/T1"}},
            },
        },
    })


@pytest.fixture
def echo_agent(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    calls: list[tuple] = []

    async def handle_internal_message(session, graph, text, requester, conversation_id):
        calls.append((requester, conversation_id))
        return f"eco: {text.strip()}"

    monkeypatch.setattr(google_chat, "handle_internal_message", handle_internal_message)
    return calls


@pytest.mark.anyio
async def test_dm_responde_con_el_texto_del_mensaje(echo_agent):
    assert await handle_event(message_event("¿Cuándo pagan?"), SESSION, GRAPH) == "eco: ¿Cuándo pagan?"


@pytest.mark.anyio
async def test_mention_responde_solo_con_el_texto_que_acompana_la_mencion(echo_agent):
    event = message_event("@Asistente ¿Cuándo pagan?", " ¿Cuándo pagan?", space_type="SPACE")

    assert await handle_event(event, SESSION, GRAPH) == "eco: ¿Cuándo pagan?"


@pytest.mark.anyio
async def test_conversation_en_mensaje_directo_es_el_space(echo_agent: list[tuple]):
    await handle_event(message_event("¿Cuándo pagan?"), SESSION, GRAPH)

    assert echo_agent == [(Requester("Ana Pérez", "ana@autofin.cl", "google_chat"), "spaces/AAA")]


@pytest.mark.anyio
async def test_conversation_en_un_space_es_el_hilo(echo_agent: list[tuple]):
    await handle_event(message_event("@Asistente ¿Bono?", " ¿Bono?", space_type="SPACE"), SESSION, GRAPH)

    assert echo_agent[0][1] == "spaces/AAA/threads/T1"


@pytest.mark.anyio
async def test_added_to_space_lo_saluda_el_coordinador(echo_agent: list[tuple]):
    event = AddonEvent.model_validate({"chat": {"addedToSpacePayload": {"space": {"name": "spaces/AAA"}}}})

    text = await handle_event(event, SESSION, GRAPH)

    assert text is not None and text.startswith("eco: [Nota del sistema") and "Saluda" in text
    assert echo_agent[0][1] == "spaces/AAA"


@pytest.mark.anyio
async def test_other_event_no_responde():
    event = AddonEvent.model_validate({"chat": {"removedFromSpacePayload": {"space": {"name": "spaces/AAA"}}}})

    assert await handle_event(event, SESSION, GRAPH) is None


def test_reply_con_texto_usa_host_app_data_action():
    assert chat_reply("Hola") == {"hostAppDataAction": {"chatDataAction": {"createMessageAction": {"message": {"text": "Hola"}}}}}
    assert chat_reply(None) == {}


# --- Cliente de la API de Chat ------------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_api_client_publica_en_el_hilo_original_con_token_bearer():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "token-de-acceso", "expires_in": 3600})
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = ChatApiClient(http, service_account_info(private_key_pem(GOOGLE_KEY)))
        await client.create_message("spaces/AAA", "Hola", thread="spaces/AAA/threads/T1")

    chat_request = requests[-1]
    assert str(chat_request.url) == (
        "https://chat.googleapis.com/v1/spaces/AAA/messages?messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD")
    assert chat_request.headers["Authorization"] == "Bearer token-de-acceso"
    assert json.loads(chat_request.content) == {"text": "Hola", "thread": {"name": "spaces/AAA/threads/T1"}}


# --- Router -------------------------------------------------------------------------------------------------------

PROPERTIES = {"google_chat_audience": AUDIENCE, "google_chat_addon_service_account": ADDON_ACCOUNT}


def override_properties(values: dict[str, str]):
    app.dependency_overrides[get_session_factory] = lambda: lambda: property_session(values)


def test_router_responde_401_sin_token():
    override_properties(PROPERTIES)
    try:
        response = TestClient(app).post("/api/v1/google-chat/events", json={"chat": {}})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


def test_router_reply_responde_con_host_app_data_action(monkeypatch: pytest.MonkeyPatch):
    seen: list[tuple] = []

    async def verify_addon_token(token, audience, service_account, http):
        seen.append((token, audience, service_account))

    async def fast_handle_event(event, session, graph):
        return "El día 30"

    monkeypatch.setattr(google_chat_router, "verify_addon_token", verify_addon_token)
    monkeypatch.setattr(google_chat_router, "handle_event", fast_handle_event)
    override_properties(PROPERTIES)
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/google-chat/events", headers={"Authorization": "Bearer token-de-google"},
                                   json=message_event("¿Cuándo pagan?").model_dump(by_alias=True))
    finally:
        app.dependency_overrides.clear()

    assert response.json() == chat_reply("El día 30")
    assert seen == [("token-de-google", AUDIENCE, ADDON_ACCOUNT)]


def test_slow_responde_procesando_y_publica_en_el_hilo_original(monkeypatch: pytest.MonkeyPatch):
    published: list[tuple[str, str | None, str]] = []

    class FakeChatApiClient:
        async def create_message(self, space: str, text: str, thread: str | None = None) -> None:
            published.append((space, thread, text))

    async def build_chat_api_client(session, http):
        return FakeChatApiClient()

    async def verify_addon_token(token, audience, service_account, http):
        return None

    async def slow_handle_event(event, session, graph):
        import asyncio
        await asyncio.sleep(0.3)
        return "respuesta lenta"

    monkeypatch.setattr(google_chat_router, "verify_addon_token", verify_addon_token)
    monkeypatch.setattr(google_chat_router, "handle_event", slow_handle_event)
    monkeypatch.setattr(google_chat_router, "build_chat_api_client", build_chat_api_client)
    override_properties(PROPERTIES | {"google_chat_sync_timeout_seconds": "0.05"})
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/google-chat/events", json=message_event("¿Bono?").model_dump(by_alias=True))
            deadline = time.monotonic() + 3
            while not published and time.monotonic() < deadline:
                time.sleep(0.05)
    finally:
        app.dependency_overrides.clear()

    assert response.json() == chat_reply(google_chat_router.PROCESSING)
    assert published == [("spaces/AAA", "spaces/AAA/threads/T1", "respuesta lenta")]
