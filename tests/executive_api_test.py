from datetime import UTC, datetime
import pytest
from fastapi.testclient import TestClient
from main import app
from src.database.session import get_session
from src.routers.executive import get_executive_repository
from src.services.executive_auth import password_hasher
from src.utils.clock import get_clock
from src.utils.exceptions.database import DatabaseUnavailableError
from tests.fakes import FakeClock, FakeExecutiveRepository, executive, property_session

PASSWORD = "Clave-Segura-123"
GENERIC_ERROR = {"detail": "Usuario o contraseña incorrectos"}


class DownRepository(FakeExecutiveRepository):
    async def find_by_username(self, username: str):
        raise DatabaseUnavailableError("conexión rechazada")


@pytest.fixture
def repo():
    repo = FakeExecutiveRepository([executive(password_hasher.hash(PASSWORD))])
    app.dependency_overrides[get_executive_repository] = lambda: repo
    app.dependency_overrides[get_clock] = lambda: FakeClock(datetime(2026, 10, 7, 12, tzinfo=UTC))
    app.dependency_overrides[get_session] = lambda: property_session({"login_max_attempts": "2"})
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
    assert TestClient(app).post("/api/v1/executives/logout").status_code == 401
