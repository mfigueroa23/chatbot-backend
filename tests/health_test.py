from fastapi.testclient import TestClient
from main import app
from src.database.session import get_session


class DownSession:
    async def execute(self, statement):
        raise ConnectionRefusedError()


def test_health_responde_503_si_la_base_de_datos_esta_caida():
    app.dependency_overrides[get_session] = DownSession
    try:
        response = TestClient(app).get("/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"Servicio": "NO DISPONIBLE", "Estado": "NO DISPONIBLE"}
