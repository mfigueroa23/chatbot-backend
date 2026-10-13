from fastapi.testclient import TestClient
from main import app


def test_chat_rechaza_un_chat_id_que_no_es_uuid():
    response = TestClient(app).post("/chat", json={"chat_id": "otro-chat", "mensaje": "Hola"})

    assert response.status_code == 422
