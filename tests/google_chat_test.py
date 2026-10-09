from types import SimpleNamespace
import pytest
import httpx
from fastapi.testclient import TestClient
from main import app
from src.interfaces.google_chat import AddonEvent
from src.routers import google_chat as google_chat_router
from src.routers.dependencies import get_assistant_deps, get_token_verifier
from src.services.google import chat_auth
from src.services.google.chat_auth import verify_addon_token
from src.services.google.chat_events import conversation_key, message_text, requester_of
from src.utils.exceptions.google_chat import InvalidGoogleTokenError
from tests.fakes import AssistantHarness

AUDIENCE = "https://chatbot.example/api/v1/google-chat/events"
ACCOUNT = "service-1@gcp-sa-gsuiteaddons.iam.gserviceaccount.com"
VALID = {"iss": "https://accounts.google.com", "email": ACCOUNT, "email_verified": True}


def space_event(text: str = "@Asistente ¿cómo pago?", argument: str = " ¿cómo pago?") -> dict:
    return {"chat": {"messagePayload": {
        "space": {"name": "spaces/AAA", "spaceType": "SPACE"},
        "message": {"text": text, "argumentText": argument, "thread": {"name": "spaces/AAA/threads/T1"}}}}}


def dm_event(text: str = "¿cómo pago?") -> dict:
    return {"chat": {"messagePayload": {
        "space": {"name": "spaces/DM1", "spaceType": "DIRECT_MESSAGE"},
        "message": {"text": text, "thread": {"name": "spaces/DM1/threads/X9"}}}}}


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

    monkeypatch.setattr(chat_auth, "get_google_certs", certs)
    monkeypatch.setattr(chat_auth.jwt, "decode", decode)
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
    assert message_text(AddonEvent.model_validate(space_event())) == " ¿cómo pago?"
    assert message_text(AddonEvent.model_validate(dm_event())) == "¿cómo pago?"


def post(harness: AssistantHarness, body: dict, valid_token: bool = True):
    async def verifier(token: str | None) -> None:
        if not valid_token:
            raise InvalidGoogleTokenError("Falta el token Bearer")

    app.dependency_overrides[get_assistant_deps] = harness.deps
    app.dependency_overrides[get_token_verifier] = lambda: verifier
    try:
        return TestClient(app).post("/api/v1/google-chat/events", json=body)
    finally:
        app.dependency_overrides.clear()


def test_endpoint_rechaza_un_token_invalido_con_401():
    harness = AssistantHarness()

    response = post(harness, space_event(), valid_token=False)

    assert response.status_code == 401 and harness.coordinator.route_calls == []


def test_endpoint_al_agregar_al_space_responde_la_bienvenida_sin_modelo():
    harness = AssistantHarness()

    response = post(harness, {"chat": {"addedToSpacePayload": {"space": {"name": "spaces/AAA"}}}})

    message = response.json()["hostAppDataAction"]["chatDataAction"]["createMessageAction"]["message"]
    assert message == {"text": "¡Hola! Soy el asistente."} and harness.coordinator.route_calls == []


def test_endpoint_responde_el_mensaje_en_el_formato_del_complemento():
    harness = AssistantHarness()

    response = post(harness, space_event())

    assert response.status_code == 200
    assert response.json() == {"hostAppDataAction": {"chatDataAction": {"createMessageAction": {
        "message": {"text": "¡Hola!"}}}}}
    assert "spaces/AAA/threads/T1" in harness.store.keys


def test_endpoint_base_de_datos_caida_responde_503():
    assert post(AssistantHarness(db_down=True), space_event()).status_code == 503


def test_endpoint_sin_token_responde_401_antes_de_leer_la_configuracion():
    app.dependency_overrides[get_assistant_deps] = AssistantHarness().deps
    try:
        # Sin override del verificador: el real rechaza la falta de token sin consultar la BD.
        response = TestClient(app).post("/api/v1/google-chat/events", json=space_event())
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


def test_requester_del_evento_llega_a_answer_en_minusculas(monkeypatch):
    seen: dict = {}

    async def fake_answer(deps, channel, conversation, text, requester=None, **kwargs):
        seen.update(requester=requester, text=text)
        return SimpleNamespace(reply="ok")

    monkeypatch.setattr(google_chat_router, "answer", fake_answer)
    event = space_event()
    event["chat"]["user"] = {"email": " JP@Autofin.cl ", "displayName": "Jefa de Proyecto"}

    response = post(AssistantHarness(), event)

    assert response.status_code == 200 and seen == {"requester": "jp@autofin.cl", "text": " ¿cómo pago?"}


def test_requester_ausente_en_el_evento_es_none():
    assert requester_of(AddonEvent.model_validate(space_event())) is None
