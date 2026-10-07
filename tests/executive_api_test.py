from datetime import UTC, datetime
import pytest
from fastapi.testclient import TestClient
from main import app
from src.database.session import get_session
from src.models.live_chat import LiveChat
from src.routers import live_chat as live_chat_router
from src.routers.executive import get_current_executive, get_executive_repository
from src.services.executive_auth import password_hasher
from src.services.realtime import get_hub
from src.utils.clock import get_clock
from src.utils.exceptions.database import DatabaseUnavailableError
from src.utils.exceptions.live_chat import ChatAlreadyAssignedError, ChatNotFoundError, ExecutiveChatLimitError, NotChatOwnerError
from tests.fakes import FakeClock, FakeExecutiveRepository, FakeHub, assigned_chat, executive, property_session

PASSWORD = "Clave-Segura-123"
GENERIC_ERROR = {"detail": "Usuario o contraseña incorrectos"}
JWT_SECRET = "clave-de-firma-de-pruebas-con-32-caracteres"


class DownRepository(FakeExecutiveRepository):
    async def find_by_username(self, username: str):
        raise DatabaseUnavailableError("conexión rechazada")


@pytest.fixture
def repo():
    repo = FakeExecutiveRepository([executive(password_hasher.hash(PASSWORD))])
    app.dependency_overrides[get_executive_repository] = lambda: repo
    app.dependency_overrides[get_clock] = lambda: FakeClock(datetime(2026, 10, 7, 12, tzinfo=UTC))
    app.dependency_overrides[get_session] = lambda: property_session({"login_max_attempts": "2", "jwt_secret": JWT_SECRET})
    yield repo
    app.dependency_overrides.clear()


def login(username: str = "ana", password: str = PASSWORD):
    return TestClient(app).post("/api/v1/executives/login", json={"username": username, "password": password})


def test_login_correcto_devuelve_token(repo: FakeExecutiveRepository):
    response = login()

    assert response.status_code == 200
    assert response.json()["token"] and response.json()["expires_at"]


def test_login_incorrecto_o_bloqueado_responde_401_generico(repo: FakeExecutiveRepository):
    wrong = [login(password="otra") for _ in range(2)]
    locked = login()

    assert [r.status_code for r in [*wrong, locked]] == [401, 401, 401]
    assert all(r.json() == GENERIC_ERROR for r in [*wrong, locked])


def test_login_con_la_base_de_datos_caida_responde_503(repo: FakeExecutiveRepository):
    app.dependency_overrides[get_executive_repository] = lambda: DownRepository()

    assert login().status_code == 503


def test_logout_revoca_la_sesion(repo: FakeExecutiveRepository):
    token = login().json()["token"]

    response = TestClient(app).post("/api/v1/executives/logout", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 204
    assert repo.sessions == {}


def test_logout_sin_token_responde_401(repo: FakeExecutiveRepository):
    response = TestClient(app).post("/api/v1/executives/logout")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_login_sin_clave_jwt_configurada_responde_503(repo: FakeExecutiveRepository):
    app.dependency_overrides[get_session] = lambda: property_session({"jwt_secret": "corta"})

    assert login().status_code == 503


def test_openapi_declara_el_bearer_jwt_en_los_endpoints_protegidos():
    schema = TestClient(app).get("/openapi.json").json()
    secured = {(path, method) for path, methods in schema["paths"].items()
               for method, operation in methods.items() if operation.get("security")}

    assert schema["components"]["securitySchemes"]["HTTPBearer"] == {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
    assert secured == {
        ("/api/v1/executives/logout", "post"),
        ("/api/v1/live-chats", "get"),
        ("/api/v1/live-chats/{chat_id}/take", "post"),
        ("/api/v1/live-chats/{chat_id}/close", "post"),
        ("/api/v1/google-chat/events", "post"),
    }


# --- live-chats ---------------------------------------------------------------------------------------------------

@pytest.fixture
def hub(repo: FakeExecutiveRepository) -> FakeHub:
    hub = FakeHub()
    app.dependency_overrides[get_hub] = lambda: hub
    app.dependency_overrides[get_current_executive] = lambda: executive(password_hasher.hash(PASSWORD))
    return hub


def raising(error: Exception):
    async def function(*args):
        raise error
    return function


def test_live_chats_lista_los_chats_en_espera(hub: FakeHub, monkeypatch: pytest.MonkeyPatch):
    async def list_waiting(session):
        return [LiveChat(id=3, customer_name="Ana", created_at=datetime(2026, 10, 7, 12, tzinfo=UTC))]

    monkeypatch.setattr(live_chat_router, "list_waiting", list_waiting)

    response = TestClient(app).get("/api/v1/live-chats", params={"status": "waiting"})

    assert response.status_code == 200
    assert response.json() == [{"id": 3, "customer_name": "Ana", "created_at": "2026-10-07T12:00:00Z"}]


def test_live_chats_sin_sesion_responde_401(repo: FakeExecutiveRepository):
    assert TestClient(app).get("/api/v1/live-chats").status_code == 401


def test_live_chats_take_devuelve_el_resumen_y_avisa_al_cliente(hub: FakeHub, monkeypatch: pytest.MonkeyPatch):
    async def take(session, chat_id, executive_id, max_chats, now):
        return assigned_chat(chat_id, executive_id)

    monkeypatch.setattr(live_chat_router, "take", take)

    response = TestClient(app).post("/api/v1/live-chats/7/take")

    assert response.status_code == 200
    assert response.json() == {"id": 7, "customer_name": "Ana", "customer_contact": "ana@correo.cl", "pending_question": "¿Cheque?"}
    assert [event.kind for event in hub.published] == ["chat_taken"]


@pytest.mark.parametrize("error, status_code, detail", [
    (ChatNotFoundError(), 404, "Chat no encontrado"),
    (ChatAlreadyAssignedError(), 409, "El chat ya fue asignado a otro ejecutivo"),
    (ExecutiveChatLimitError(), 409, "Alcanzaste el máximo de chats simultáneos"),
    (DatabaseUnavailableError("caída"), 503, "Servicio no disponible"),
])
def test_live_chats_take_errores(hub: FakeHub, monkeypatch: pytest.MonkeyPatch, error: Exception, status_code: int, detail: str):
    monkeypatch.setattr(live_chat_router, "take", raising(error))

    response = TestClient(app).post("/api/v1/live-chats/7/take")

    assert (response.status_code, response.json()["detail"]) == (status_code, detail)


def test_live_chats_close_de_otro_ejecutivo_responde_403(hub: FakeHub, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(live_chat_router, "close", raising(NotChatOwnerError()))

    assert TestClient(app).post("/api/v1/live-chats/7/close").status_code == 403


def test_live_chats_close_avisa_al_cliente(hub: FakeHub, monkeypatch: pytest.MonkeyPatch):
    async def close(session, chat_id, executive_id, now):
        return assigned_chat(chat_id, executive_id)

    monkeypatch.setattr(live_chat_router, "close", close)

    assert TestClient(app).post("/api/v1/live-chats/7/close").status_code == 204
    assert [(event.kind, event.reason) for event in hub.published] == [("chat_closed", "executive")]


def test_live_chats_con_la_base_de_datos_caida_responde_503(hub: FakeHub, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(live_chat_router, "list_waiting", raising(DatabaseUnavailableError("caída")))

    assert TestClient(app).get("/api/v1/live-chats").status_code == 503
