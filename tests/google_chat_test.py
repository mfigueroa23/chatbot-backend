import httpx
import pytest
from fastapi.testclient import TestClient
from main import app
from src.interfaces.google_chat import AddonEvent
from src.services import google_chat
from src.services.google_chat import conversation_key, message_text, verify_addon_token
from src.utils.exceptions.google_chat import InvalidGoogleTokenError

AUDIENCE = "https://chatbot.example/api/v1/google-chat/events"
ACCOUNT = "service-1@gcp-sa-gsuiteaddons.iam.gserviceaccount.com"
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


def test_endpoint_sin_token_responde_401_antes_de_leer_la_configuracion():
    response = TestClient(app).post("/api/v1/google-chat/events", json=space_event())

    assert response.status_code == 401
