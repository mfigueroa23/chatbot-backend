import json
import logging
import uuid
import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from src.services.edr.document import EdrConfig
from src.services.edr.job import EDR_FAILED, EdrJobDeps, EdrRequest, run_edr_job
from src.services.edr.store import EdrRecord
from src.services.property import Properties
from tests.chat_media_test import SERVICE_ACCOUNT, TOKEN_URI
from tests.fakes import FakeEdrRepository, FakeEdrWriter

CONFIG = EdrConfig("<h1>{{ edr.titulo }}</h1><p>{{ edr.objetivo_general }}</p>", "carpeta-1", SERVICE_ACCOUNT)
PROPERTIES = Properties({"edr_job_timeout_seconds": "5", "edr_history_messages": "10"})
CONVERSATION = uuid.uuid4()
LINK = "https://docs.google.com/document/d/doc-1"


class Google:
    """Drive y la API de Chat con MockTransport: guarda cada request y puede fallar en Drive."""

    def __init__(self, drive_status: int = 200):
        self.drive_status = drive_status
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == TOKEN_URI:
                return httpx.Response(200, json={"access_token": "ya29.token"})
            self.requests.append(request)
            if request.url.host == "chat.googleapis.com":
                return httpx.Response(200, json={"name": "spaces/AAA/messages/1"})
            return httpx.Response(self.drive_status, json={"id": "doc-1", "webViewLink": LINK})
        return httpx.MockTransport(handler)

    def drive(self) -> list[httpx.Request]:
        return [request for request in self.requests if request.url.host == "www.googleapis.com"]

    def posted(self) -> list[str]:
        return [json.loads(request.content)["text"] for request in self.requests if request.url.host == "chat.googleapis.com"]


def request(text: str = "Arma el EDR de DAIA-250", epic: str | None = "DAIA-250", new: bool = False,
            message: str = "Arma el EDR de DAIA-250") -> EdrRequest:
    return EdrRequest(CONVERSATION, "spaces/AAA/threads/T1", text, message, epic, new)


async def run(repository: FakeEdrRepository, writer: FakeEdrWriter, google: Google, edr_request: EdrRequest,
              epics: list[str] | None = None) -> None:
    async def read_epic(key: str) -> str:
        (epics if epics is not None else []).append(key)
        return '<informacion fuente="ticket de Jira">\nDAIA-250 · PoC - Chatbot SAC\n</informacion>'

    await run_edr_job(edr_request, CONFIG, PROPERTIES, EdrJobDeps(repository, writer, read_epic, google.transport()))


@pytest.mark.anyio
async def test_crea_el_doc_con_la_conversacion_y_la_epica_y_publica_el_enlace():
    repository = FakeEdrRepository([HumanMessage("El PO es Ana"), AIMessage("Anotado")])
    writer, google, epics = FakeEdrWriter('{"titulo": "PoC Chatbot", "objetivo_general": "Responder FAQ"}'), Google(), []

    await run(repository, writer, google, request(), epics)

    sent = str(writer.calls[0][1].content)
    assert epics == ["DAIA-250"] and "Persona: El PO es Ana" in sent and "DAIA-250 · PoC" in sent
    assert "Persona: Arma el EDR de DAIA-250" in sent and "Eres el redactor de EDR." in str(writer.calls[0][0].content)
    assert google.drive()[0].method == "POST" and "<h1>PoC Chatbot</h1>" in google.drive()[0].content.decode()
    assert repository.records[CONVERSATION] == [EdrRecord("doc-1", LINK, "PoC Chatbot", repository.records[CONVERSATION][0].content)]
    assert google.posted() == repository.replies and LINK in repository.replies[0] and "«PoC Chatbot»" in repository.replies[0]


@pytest.mark.anyio
async def test_un_cambio_actualiza_el_mismo_doc_con_el_edr_actual():
    repository = FakeEdrRepository()
    repository.records[CONVERSATION] = [EdrRecord("doc-1", LINK, "PoC", {"titulo": "PoC", "objetivo_general": "v1"})]
    writer, google = FakeEdrWriter('{"titulo": "PoC", "objetivo_general": "v2"}'), Google()

    await run(repository, writer, google, request("Cambia el objetivo a v2", epic=None))

    assert '"objetivo_general": "v1"' in str(writer.calls[0][1].content)
    assert google.drive()[0].method == "PATCH" and google.drive()[0].url.path.endswith("/files/doc-1")
    assert len(repository.records[CONVERSATION]) == 1 and repository.records[CONVERSATION][0].content["objetivo_general"] == "v2"
    assert repository.replies[0].startswith("Listo, actualicé el EDR")


@pytest.mark.anyio
async def test_nuevo_crea_otro_doc_aunque_haya_uno_en_la_conversacion():
    repository = FakeEdrRepository()
    repository.records[CONVERSATION] = [EdrRecord("doc-0", LINK, "Otro", {"titulo": "Otro"})]
    google = Google()

    await run(repository, FakeEdrWriter(), google, request(epic=None, new=True))

    assert google.drive()[0].method == "POST" and [record.drive_file_id for record in repository.records[CONVERSATION]] == ["doc-0", "doc-1"]


@pytest.mark.anyio
async def test_json_invalido_se_corrige_una_vez():
    writer = FakeEdrWriter("esto no es json", '```json\n{"titulo": "Corregido"}\n```')
    repository = FakeEdrRepository()

    await run(repository, writer, Google(), request(epic=None))

    assert len(writer.calls) == 2 and "no es un EDR válido" in str(writer.calls[1][-1].content)
    assert "«Corregido»" in repository.replies[0]


@pytest.mark.anyio
async def test_dos_respuestas_invalidas_publican_que_no_se_guardo():
    repository, google = FakeEdrRepository(), Google()

    await run(repository, FakeEdrWriter('{"sin_titulo": true}'), google, request(epic=None))

    assert repository.replies == [EDR_FAILED] and google.drive() == [] and CONVERSATION not in repository.records


@pytest.mark.anyio
async def test_drive_caido_no_deja_fila_ni_afirma_que_se_guardo(caplog):
    repository, google = FakeEdrRepository(), Google(drive_status=403)

    with caplog.at_level(logging.INFO, logger="src"):
        await run(repository, FakeEdrWriter('{"titulo": "Secreto de Ana"}'), google, request(epic=None))

    assert repository.replies == [EDR_FAILED] and google.posted() == [EDR_FAILED] and CONVERSATION not in repository.records
    assert "HTTPStatusError" in caplog.text and "Secreto de Ana" not in caplog.text


@pytest.mark.anyio
async def test_supera_el_tope_y_publica_que_no_pudo():
    repository = FakeEdrRepository()
    properties = Properties({"edr_job_timeout_seconds": "0"})

    async def read_epic(key: str) -> str:
        return ""

    await run_edr_job(request(epic=None), CONFIG, properties,
                      EdrJobDeps(repository, FakeEdrWriter(delay=0.1), read_epic, Google().transport()))

    assert repository.replies == [EDR_FAILED]


@pytest.mark.anyio
async def test_el_mensaje_actual_no_se_repite_si_ya_esta_en_el_historial():
    repository = FakeEdrRepository([HumanMessage("Arma el EDR de DAIA-250")])
    writer = FakeEdrWriter()

    await run(repository, writer, Google(), request(epic=None))

    assert str(writer.calls[0][1].content).count("Persona: Arma el EDR de DAIA-250") == 1
