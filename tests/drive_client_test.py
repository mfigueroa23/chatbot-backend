import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.auth import jwt
import json
from src.services.drive_client import DOCX_EXPORT, DriveClient, DriveFile, DriveUpload
from src.utils.exceptions.drive import DriveFileNotAccessibleError
from tests.fakes import service_account_info

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()


def drive(routes: dict[str, httpx.Response], requests: list[httpx.Request]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "token-drive", "expires_in": 3600})
        for prefix, response in routes.items():
            if str(request.url).startswith(prefix):
                return response
        return httpx.Response(500)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


FILE = "https://www.googleapis.com/drive/v3/files/F1"


@pytest.mark.anyio
async def test_lectura_metadatos_y_descarga_de_un_archivo():
    requests: list[httpx.Request] = []
    routes = {f"{FILE}?alt=media": httpx.Response(200, content=b"datos"),
              f"{FILE}?fields": httpx.Response(200, json={"id": "F1", "name": "Contrato.pdf", "mimeType": "application/pdf",
                                                          "size": "2048"})}

    async with drive(routes, requests) as http:
        client = DriveClient(http, service_account_info(PEM))
        metadata = await client.file_metadata("F1")
        data = await client.download("F1")

    assert metadata == DriveFile("F1", "Contrato.pdf", "application/pdf", 2048)
    assert data == b"datos"
    assert all(r.headers.get("Authorization") == "Bearer token-drive" for r in requests if r.url.host == "www.googleapis.com")
    assertion = dict(httpx.QueryParams(requests[0].content.decode()))["assertion"]
    assert jwt.decode(assertion, verify=False)["scope"] == "https://www.googleapis.com/auth/drive"
    assert "supportsAllDrives=true" in str(requests[1].url)


@pytest.mark.anyio
async def test_lectura_exporta_un_documento_nativo():
    requests: list[httpx.Request] = []
    routes = {f"{FILE}/export": httpx.Response(200, content=b"docx")}

    async with drive(routes, requests) as http:
        data = await DriveClient(http, service_account_info(PEM)).export("F1", DOCX_EXPORT)

    assert data == b"docx" and httpx.URL(str(requests[-1].url)).params["mimeType"] == DOCX_EXPORT


@pytest.mark.anyio
@pytest.mark.parametrize("status", [403, 404])
async def test_lectura_sin_acceso_lanza_archivo_no_accesible(status):
    routes = {FILE: httpx.Response(status, json={"error": {"code": status}})}

    async with drive(routes, []) as http:
        client = DriveClient(http, service_account_info(PEM))

        with pytest.raises(DriveFileNotAccessibleError):
            await client.file_metadata("F1")


def test_lectura_cuenta_del_asistente_para_compartir():
    client = DriveClient(httpx.AsyncClient(), service_account_info(PEM))

    assert client.account_email == "bot@proyecto.iam.gserviceaccount.com"



UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"


@pytest.mark.anyio
async def test_escritura_crea_un_google_doc_desde_html_en_la_carpeta():
    requests: list[httpx.Request] = []
    routes = {UPLOAD: httpx.Response(200, json={"id": "DOC1", "webViewLink": "https://docs.google.com/document/d/DOC1/edit"})}

    async with drive(routes, requests) as http:
        upload = await DriveClient(http, service_account_info(PEM)).create_document_from_html("EDR DAIA-52", "CARPETA",
                                                                                              "<h1>EDR</h1>")

    assert upload == DriveUpload("DOC1", "https://docs.google.com/document/d/DOC1/edit")
    request = requests[-1]
    assert request.method == "POST" and request.url.params["uploadType"] == "multipart"
    assert request.url.params["supportsAllDrives"] == "true"
    body = request.content.decode()
    metadata = json.loads(body.split("\r\n\r\n")[1].split("\r\n--")[0])
    assert metadata == {"name": "EDR DAIA-52", "mimeType": "application/vnd.google-apps.document", "parents": ["CARPETA"]}
    assert "<h1>EDR</h1>" in body and "text/html" in body


@pytest.mark.anyio
async def test_escritura_reemplaza_el_contenido_del_mismo_documento():
    requests: list[httpx.Request] = []
    routes = {f"{UPLOAD}/DOC1": httpx.Response(200, json={"id": "DOC1", "webViewLink": "https://docs.google.com/d/DOC1"})}

    async with drive(routes, requests) as http:
        upload = await DriveClient(http, service_account_info(PEM)).replace_document_html("DOC1", "<h1>v2</h1>")

    assert upload == DriveUpload("DOC1", "https://docs.google.com/d/DOC1")
    assert requests[-1].method == "PATCH" and requests[-1].content == b"<h1>v2</h1>"
