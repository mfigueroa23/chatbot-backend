import logging
import time as clock_time
from datetime import UTC, datetime, time
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect
from main import app
from src.agents import strategies
from src.database.session import get_session_factory
from src.interfaces.web_chat import ContactMessage, HumanResponse, Ping, RequestHuman, TextMessage, UserMessage, client_message_adapter
from src.models.live_chat import LiveChat, LiveChatStatus
from src.models.live_chat_message import LiveChatMessage, MessageSender
from src.models.official_channel import OfficialChannel
from src.models.web_session import WebPhase, WebSession
from src.routers import web_chat
from src.services import chat_orchestrator
from src.services.realtime import Event, get_hub
from src.utils.clock import get_clock
from src.utils.exceptions.database import DatabaseUnavailableError
from tests.fakes import FakeAgentLLM, FakeClock, FakeHub, assigned_chat, property_session, web_session

IN_HOURS = datetime(2026, 10, 7, 15, tzinfo=UTC)
CHANNELS = [{"label": "Teléfono", "value": "600 123 4567"}]


@pytest.mark.parametrize("raw, expected", [
    ({"type": "message", "text": "Hola"}, UserMessage),
    ({"type": "human_response", "accept": True}, HumanResponse),
    ({"type": "contact", "name": "Ana", "email": "ana@correo.cl"}, ContactMessage),
    ({"type": "request_human"}, RequestHuman),
    ({"type": "ping"}, Ping),
])
def test_parse_mensajes_del_cliente(raw: dict, expected: type):
    assert isinstance(client_message_adapter.validate_python(raw), expected)


def test_parse_tipo_desconocido_falla():
    with pytest.raises(ValidationError):
        client_message_adapter.validate_python({"type": "hack"})


class Calls:
    def __init__(self, session: WebSession):
        self.session = session
        self.hub = FakeHub()
        self.disconnected: list = []
        self.enqueued: list = []


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch):
    current = web_session()
    calls = Calls(current)

    async def get_or_create(session, clock, session_id, retention_days):
        return current

    async def admit(session, clock, session_id, max_sessions):
        return True

    async def get_web_session(session, session_id):
        return current

    async def heartbeat(session, clock, session_id):
        return None

    async def mark_disconnected(session, session_id):
        calls.disconnected.append(session_id)

    async def get_official_channels(session):
        return [OfficialChannel(label="Teléfono", value="600 123 4567")]

    async def load_schedule(session):
        return {weekday: (time(9, 0), time(18, 0)) for weekday in range(5)}, set()

    async def get_open_chat(session, web_session_id):
        return None

    async def customer_disconnected(session, web_session_id, now):
        return None

    async def enqueue(session, web_session_id, name, contact, question):
        calls.enqueued.append((name, contact, question))
        return LiveChat(id=1, web_session_id=web_session_id, status=LiveChatStatus.waiting)

    for name, function in [("get_or_create", get_or_create), ("admit", admit), ("get_web_session", get_web_session),
                           ("heartbeat", heartbeat), ("mark_disconnected", mark_disconnected),
                           ("get_official_channels", get_official_channels), ("get_open_chat", get_open_chat),
                           ("customer_disconnected", customer_disconnected)]:
        monkeypatch.setattr(web_chat, name, function)
    monkeypatch.setattr(chat_orchestrator, "get_official_channels", get_official_channels)
    monkeypatch.setattr(chat_orchestrator, "enqueue", enqueue)
    monkeypatch.setattr(strategies, "load_schedule", load_schedule)
    monkeypatch.setattr(strategies, "get_official_channels", get_official_channels)
    app.dependency_overrides[get_session_factory] = lambda: lambda: property_session({})
    app.dependency_overrides[get_clock] = lambda: FakeClock(IN_HOURS)
    app.dependency_overrides[get_hub] = lambda: calls.hub
    yield calls
    app.dependency_overrides.clear()


def wait_for(condition) -> None:
    deadline = clock_time.monotonic() + 3
    while not condition() and clock_time.monotonic() < deadline:
        clock_time.sleep(0.02)


def test_connect_envia_el_id_de_sesion(calls: Calls):
    with TestClient(app) as client, client.websocket_connect("/ws/v1/chat") as ws:
        assert ws.receive_json() == {"type": "session", "session_id": str(web_session().id)}


def test_busy_con_50_sesiones_muestra_canales_y_cierra(calls: Calls, monkeypatch: pytest.MonkeyPatch):
    async def admit(session, clock, session_id, max_sessions):
        return False

    monkeypatch.setattr(web_chat, "admit", admit)
    with TestClient(app) as client, client.websocket_connect("/ws/v1/chat") as ws:
        assert ws.receive_json() == {"type": "busy", "channels": CHANNELS}
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == 1013


def test_message_responde_con_el_orquestador(calls: Calls, monkeypatch: pytest.MonkeyPatch):
    async def handle_web_message(session, graph, current, text, clock):
        return [TextMessage(from_="bot", text=f"eco: {text}")]

    monkeypatch.setattr(web_chat, "handle_web_message", handle_web_message)
    with TestClient(app) as client, client.websocket_connect("/ws/v1/chat") as ws:
        ws.receive_json()
        ws.send_json({"type": "ping"})
        ws.send_json({"type": "message", "text": "Hola"})
        assert ws.receive_json() == {"type": "message", "from": "bot", "text": "eco: Hola"}


def test_disconnect_marca_la_sesion_desconectada(calls: Calls, monkeypatch: pytest.MonkeyPatch):
    async def handle_web_message(session, graph, current, text, clock):
        import asyncio
        await asyncio.sleep(0.2)
        return [TextMessage(from_="bot", text="respuesta descartada")]

    monkeypatch.setattr(web_chat, "handle_web_message", handle_web_message)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/v1/chat") as ws:
            ws.receive_json()
            ws.send_json({"type": "message", "text": "Hola"})
        wait_for(lambda: calls.disconnected)

    assert calls.disconnected == [web_session().id]


def test_db_down_al_conectar_responde_no_disponible_y_lo_registra(
    calls: Calls, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    async def get_or_create(session, clock, session_id, retention_days):
        raise DatabaseUnavailableError("conexión rechazada")

    monkeypatch.setattr(web_chat, "get_or_create", get_or_create)
    caplog.set_level(logging.ERROR)
    with TestClient(app) as client, client.websocket_connect("/ws/v1/chat") as ws:
        assert ws.receive_json()["code"] == "service_unavailable"
    assert "conexión rechazada" in caplog.text


def test_request_human_dentro_de_horario_ofrece_un_ejecutivo(calls: Calls):
    with TestClient(app) as client, client.websocket_connect("/ws/v1/chat") as ws:
        ws.receive_json()
        ws.send_json({"type": "request_human"})
        assert ws.receive_json()["type"] == "message"
        assert ws.receive_json() == {"type": "offer_human"}


def test_offer_aceptada_pide_los_datos_y_contact_valido_entra_en_la_queue(calls: Calls):
    with TestClient(app) as client, client.websocket_connect("/ws/v1/chat") as ws:
        ws.receive_json()
        ws.send_json({"type": "request_human"})
        ws.receive_json()
        ws.receive_json()
        ws.send_json({"type": "human_response", "accept": True})
        assert ws.receive_json() == {"type": "request_contact", "attempt": 1}
        ws.send_json({"type": "contact", "name": "Ana Pérez", "phone": "+56 9 1234 5678"})
        assert ws.receive_json() == {"type": "queued"}

    assert calls.enqueued[0][:2] == ("Ana Pérez", "+56 9 1234 5678")
    assert calls.session.phase == WebPhase.queued


def test_reject_de_la_oferta_pide_reformular_y_muestra_canales(calls: Calls):
    with TestClient(app) as client, client.websocket_connect("/ws/v1/chat") as ws:
        ws.receive_json()
        ws.send_json({"type": "request_human"})
        ws.receive_json()
        ws.receive_json()
        ws.send_json({"type": "human_response", "accept": False})
        assert "reformula" in ws.receive_json()["text"]
        assert ws.receive_json() == {"type": "official_channels", "channels": CHANNELS}


def test_contact_invalido_tres_veces_muestra_canales_sin_entrar_en_la_cola(calls: Calls):
    with TestClient(app) as client, client.websocket_connect("/ws/v1/chat") as ws:
        ws.receive_json()
        ws.send_json({"type": "request_human"})
        ws.receive_json()
        ws.receive_json()
        ws.send_json({"type": "human_response", "accept": True})
        ws.receive_json()
        replies = []
        for _ in range(3):
            ws.send_json({"type": "contact", "name": "Ana", "email": "no-es-correo"})
            replies.append(ws.receive_json())
        assert replies[:2] == [{"type": "request_contact", "attempt": 2}, {"type": "request_contact", "attempt": 3}]
        assert replies[2]["type"] == "message"
        assert ws.receive_json() == {"type": "official_channels", "channels": CHANNELS}

    assert calls.enqueued == []


# --- Fase en vivo -------------------------------------------------------------------------------------------------

@pytest.fixture
def live(calls: Calls, monkeypatch: pytest.MonkeyPatch):
    calls.session.phase = WebPhase.live
    llm = FakeAgentLLM(area_ids=[1], answers={1: "no debería responder"})

    async def build_agent_context(session):
        raise AssertionError("En la fase en vivo no se llama al agente")

    async def get_open_chat(session, web_session_id):
        return assigned_chat(7, 5)

    async def post_message(session, chat_id, sender, content):
        return LiveChatMessage(id=43, live_chat_id=chat_id, sender=sender, content=content)

    async def get_message(session, message_id):
        return LiveChatMessage(id=message_id, live_chat_id=7, sender=MessageSender.executive, content="Hola, soy Pedro")

    async def customer_disconnected(session, web_session_id, now):
        return assigned_chat(7, 5)

    monkeypatch.setattr(chat_orchestrator, "build_agent_context", build_agent_context)
    for name, function in [("get_open_chat", get_open_chat), ("post_message", post_message), ("get_message", get_message),
                           ("customer_disconnected", customer_disconnected)]:
        monkeypatch.setattr(web_chat, name, function)
    return llm


def test_live_el_mensaje_del_cliente_va_al_ejecutivo_sin_llamar_al_agente(calls: Calls, live: FakeAgentLLM):
    with TestClient(app) as client, client.websocket_connect("/ws/v1/chat") as ws:
        ws.receive_json()
        ws.send_json({"type": "message", "text": "¿Siguen ahí?"})
        wait_for(lambda: any(event.kind == "customer_message" for event in calls.hub.published))

    assert live.calls == []
    event = calls.hub.published[0]
    assert (event.kind, event.chat_id, event.executive_id, event.message_id) == ("customer_message", 7, 5, 43)


def test_live_los_eventos_del_ejecutivo_llegan_al_cliente(calls: Calls, live: FakeAgentLLM):
    session_id = str(web_session().id)
    with TestClient(app) as client, client.websocket_connect("/ws/v1/chat") as ws:
        ws.receive_json()
        assert client.portal is not None
        for event in [Event("chat_taken", 7, web_session_id=session_id),
                      Event("executive_message", 7, web_session_id=session_id, message_id=44),
                      Event("executive_disconnected", 7, web_session_id=session_id),
                      Event("chat_closed", 7, web_session_id=session_id, reason="executive")]:
            client.portal.call(calls.hub.dispatch, event.to_payload())

        assert ws.receive_json() == {"type": "executive_joined"}
        assert ws.receive_json() == {"type": "message", "from": "executive", "text": "Hola, soy Pedro"}
        assert ws.receive_json() == {"type": "executive_disconnected", "return_within_minutes": 60}
        assert ws.receive_json() == {"type": "chat_closed", "reason": "executive"}


def test_live_la_desconexion_del_cliente_cierra_el_chat_y_avisa_al_ejecutivo(calls: Calls, live: FakeAgentLLM):
    with TestClient(app) as client:
        with client.websocket_connect("/ws/v1/chat") as ws:
            ws.receive_json()
        wait_for(lambda: calls.hub.published)

    assert [(e.kind, e.executive_id, e.reason) for e in calls.hub.published] == [("chat_closed", 5, "customer_left")]
