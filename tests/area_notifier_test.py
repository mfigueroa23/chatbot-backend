import json
import logging
import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from src.services.area_notifier import AreaNotifier, Requester, format_request, format_unanswered
from src.services.google_chat import ChatApiClient
from src.utils.exceptions.notification import NotificationDeliveryError
from tests.fakes import property_session, service_account_info

KEY_PEM = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
SERVICE_ACCOUNT = service_account_info(KEY_PEM)
COLLABORATOR = Requester("Ana Pérez", "ana@autofin.cl", "google_chat")
CUSTOMER = Requester("Juan Soto", "+56 9 1234 5678", "web")


def chat_transport(requests: list[httpx.Request], status_code: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "token-de-acceso", "expires_in": 3600})
        return httpx.Response(status_code, json={})
    return httpx.MockTransport(handler)


@pytest.mark.anyio
async def test_create_message_sin_hilo_publica_en_un_hilo_nuevo():
    requests: list[httpx.Request] = []

    async with httpx.AsyncClient(transport=chat_transport(requests)) as http:
        await ChatApiClient(http, SERVICE_ACCOUNT).create_message("spaces/GESTION", "Nueva solicitud")

    assert str(requests[-1].url) == "https://chat.googleapis.com/v1/spaces/GESTION/messages"
    assert json.loads(requests[-1].content) == {"text": "Nueva solicitud"}


def notifier(requests: list[httpx.Request], status_code: int = 200) -> AreaNotifier:
    values = {"google_chat_service_account_json": json.dumps(SERVICE_ACCOUNT)}
    return AreaNotifier(lambda: property_session(values), transport=chat_transport(requests, status_code))


@pytest.mark.anyio
async def test_notify_publica_el_texto_en_el_space_del_area():
    requests: list[httpx.Request] = []

    await notifier(requests).notify("spaces/GESTION", "Nueva solicitud")

    assert requests[-1].url.path == "/v1/spaces/GESTION/messages"


@pytest.mark.anyio
async def test_notify_con_error_http_lanza_notification_delivery_error():
    with pytest.raises(NotificationDeliveryError):
        await notifier([], status_code=403).notify("spaces/GESTION", "Nueva solicitud")


@pytest.mark.anyio
async def test_notify_sin_cuenta_de_servicio_lanza_notification_delivery_error():
    with pytest.raises(NotificationDeliveryError):
        await AreaNotifier(lambda: property_session({})).notify("spaces/GESTION", "Nueva solicitud")


@pytest.mark.anyio
async def test_notify_no_registra_el_texto_en_el_log(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG)

    await notifier([]).notify("spaces/GESTION", "RUT 12345678-5 del cliente")
    with pytest.raises(NotificationDeliveryError):
        await notifier([], status_code=500).notify("spaces/GESTION", "RUT 12345678-5 del cliente")

    assert "12345678-5" not in caplog.text


def test_format_request_incluye_procedimiento_datos_e_identidad():
    text = format_request("Copia del contrato", [("RUT del titular", "12345678-5"), ("Patente", "ABCD12")],
                          CUSTOMER, "Necesito una copia de mi contrato")

    assert "Nueva solicitud: Copia del contrato" in text
    assert "Canal: chat web" in text
    assert "Solicitante: Juan Soto · +56 9 1234 5678" in text
    assert "RUT del titular: 12345678-5" in text and "Patente: ABCD12" in text
    assert "Mensaje original: Necesito una copia de mi contrato" in text


def test_format_unanswered_incluye_area_y_colaborador():
    text = format_unanswered("¿Cuándo pagan el bono?", "Remuneraciones", COLLABORATOR)

    assert "Consulta sin respuesta del asistente" in text
    assert "Área: Remuneraciones" in text
    assert "Colaborador: Ana Pérez <ana@autofin.cl>" in text
    assert "Consulta: ¿Cuándo pagan el bono?" in text
    assert "Área: sin área" in format_unanswered("¿Dónde está el casino?", None, COLLABORATOR)
