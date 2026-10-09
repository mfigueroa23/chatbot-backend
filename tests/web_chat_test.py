import uuid
from types import SimpleNamespace
from fastapi.testclient import TestClient
from main import app
from src.routers import web_chat as web_chat_router
from src.routers.dependencies import get_assistant_deps
from src.services.message_validation import TOO_LONG_MESSAGE
from tests.fakes import AssistantHarness


def post(harness: AssistantHarness, body: dict):
    app.dependency_overrides[get_assistant_deps] = harness.deps
    try:
        return TestClient(app).post("/api/v1/chat", json=body)
    finally:
        app.dependency_overrides.clear()


def test_sin_session_id_devuelve_una_sesion_nueva_y_la_respuesta():
    response = post(AssistantHarness(), {"message": "hola"})

    assert response.status_code == 200
    assert uuid.UUID(response.json()["session_id"]) and response.json()["reply"] == "¡Hola!"


def test_con_una_sesion_existente_la_mantiene():
    harness = AssistantHarness()
    first = post(harness, {"message": "hola"}).json()["session_id"]

    second = post(harness, {"session_id": first, "message": "otra vez"})

    assert second.json()["session_id"] == first


def test_mensaje_largo_responde_200_con_el_aviso_del_limite():
    response = post(AssistantHarness(), {"message": "a" * 5001})

    assert response.status_code == 200 and response.json()["reply"] == TOO_LONG_MESSAGE


def test_base_de_datos_caida_responde_503():
    response = post(AssistantHarness(db_down=True), {"message": "hola"})

    assert response.status_code == 503 and response.json() == {"detail": "Servicio no disponible"}


def test_el_web_llama_a_answer_como_anonimo_requester(monkeypatch):
    seen: dict = {}

    async def fake_answer(deps, channel, conversation, text, requester="sin pasar", **kwargs):
        seen.update(requester=requester, extra=kwargs)
        return SimpleNamespace(conversation_id=uuid.uuid4(), reply="ok")

    monkeypatch.setattr(web_chat_router, "answer", fake_answer)

    assert post(AssistantHarness(), {"message": "hola"}).status_code == 200
    assert seen == {"requester": None, "extra": {}}
