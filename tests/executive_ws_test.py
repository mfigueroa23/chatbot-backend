import time
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from main import app
from src.database.session import get_session_factory
from src.models.live_chat_message import LiveChatMessage, MessageSender
from src.routers import executive as executive_router
from src.services.executive_auth import password_hasher
from src.services.realtime import Event, get_hub
from src.utils.exceptions.auth import InvalidSessionError
from tests.fakes import FakeHub, assigned_chat, executive, property_session

EXECUTIVE = executive(password_hasher.hash("Clave-Segura-123"))


class Calls:
    def __init__(self):
        self.hub = FakeHub()
        self.disconnected: list[int] = []
        self.posted: list[tuple[int, str]] = []
        self.valid_tokens = {"token-valido"}


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch):
    calls = Calls()

    async def authenticate(repo, clock, secret, token):
        if token not in calls.valid_tokens:
            raise InvalidSessionError()
        return EXECUTIVE

    async def resume(session, executive_id, now, window):
        return [assigned_chat(7, executive_id)]

    async def mark_executive_disconnected(session, executive_id, now):
        calls.disconnected.append(executive_id)
        return [assigned_chat(7, executive_id)]

    async def get_assigned_chat(session, chat_id, executive_id):
        return assigned_chat(chat_id, executive_id)

    async def post_message(session, chat_id, sender, content):
        calls.posted.append((chat_id, content))
        return LiveChatMessage(id=42, live_chat_id=chat_id, sender=sender, content=content)

    async def get_message(session, message_id):
        return LiveChatMessage(id=message_id, live_chat_id=7, sender=MessageSender.customer, content="Hola, ¿siguen ahí?")

    for name, function in [("authenticate", authenticate), ("resume", resume),
                           ("mark_executive_disconnected", mark_executive_disconnected),
                           ("get_assigned_chat", get_assigned_chat), ("post_message", post_message),
                           ("get_message", get_message)]:
        monkeypatch.setattr(executive_router, name, function)
    app.dependency_overrides[get_session_factory] = lambda: lambda: property_session({"jwt_secret": "clave-de-firma-de-pruebas-con-32-caracteres"})
    app.dependency_overrides[get_hub] = lambda: calls.hub
    yield calls
    app.dependency_overrides.clear()




def test_sin_token_valido_cierra_con_4401(calls: Calls):
    with TestClient(app) as client, client.websocket_connect("/ws/v1/executive") as ws:
        ws.send_json({"type": "auth", "token": "inventado"})
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == 4401


def test_retoma_envia_los_chats_asignados(calls: Calls):
    with TestClient(app) as client, client.websocket_connect("/ws/v1/executive") as ws:
        ws.send_json({"type": "auth", "token": "token-valido"})
        assert ws.receive_json() == {"type": "assigned_chats", "chats": [
            {"id": 7, "customer_name": "Ana", "customer_contact": "ana@correo.cl", "pending_question": "¿Cheque?"}]}


def test_mensaje_del_ejecutivo_se_publica_en_el_hub(calls: Calls):
    with TestClient(app) as client, client.websocket_connect("/ws/v1/executive") as ws:
        ws.send_json({"type": "auth", "token": "token-valido"})
        ws.receive_json()
        ws.send_json({"type": "message", "chat_id": 7, "text": "Hola, soy Pedro"})
        deadline = time.monotonic() + 3
        while not calls.hub.published and time.monotonic() < deadline:
            time.sleep(0.02)

    assert calls.posted == [(7, "Hola, soy Pedro")]
    assert (calls.hub.published[0].kind, calls.hub.published[0].message_id) == ("executive_message", 42)


def test_mensajes_del_cliente_y_aviso_de_chat_cerrado_llegan_al_ejecutivo(calls: Calls):
    with TestClient(app) as client, client.websocket_connect("/ws/v1/executive") as ws:
        ws.send_json({"type": "auth", "token": "token-valido"})
        ws.receive_json()
        assert client.portal is not None
        client.portal.call(calls.hub.dispatch, Event("customer_message", 7, executive_id=EXECUTIVE.id, message_id=43).to_payload())
        assert ws.receive_json() == {"type": "message", "chat_id": 7, "text": "Hola, ¿siguen ahí?"}
        client.portal.call(calls.hub.dispatch, Event("chat_closed", 7, executive_id=EXECUTIVE.id, reason="customer_left").to_payload())
        assert ws.receive_json() == {"type": "chat_closed", "chat_id": 7, "reason": "customer_left"}


def test_sesion_caducada_se_trata_como_desconexion(calls: Calls):
    with TestClient(app) as client, client.websocket_connect("/ws/v1/executive") as ws:
        ws.send_json({"type": "auth", "token": "token-valido"})
        ws.receive_json()
        calls.valid_tokens.clear()
        ws.send_json({"type": "ping"})
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()

    assert closed.value.code == 4401
    assert calls.disconnected == [EXECUTIVE.id]
    assert [event.kind for event in calls.hub.published] == ["executive_disconnected"]
