import asyncio
import base64
import json
import uuid
from typing import Any
import pytest
from pydantic import BaseModel
from src.agents.tools import edr as edr_module
from src.agents.tools.edr import IN_PROGRESS, NO_EDR, NOT_CONFIGURED, ONLY_GOOGLE_CHAT, STARTED, edr_tools
from src.agents.tools.registry import AreaTool, ToolContext, code_tool
from src.services.edr.store import EdrRecord
from src.services.property import Properties
from tests.chat_media_test import SERVICE_ACCOUNT
from tests.edr_job_test import Google
from tests.fakes import FakeEdrRepository, FakeEdrWriter

TEMPLATE = base64.b64encode(b"<h1>{{ edr.titulo }}</h1>").decode()
PROPERTIES = {"edr_template_base64": TEMPLATE, "edr_drive_folder_id": "carpeta-1",
              "google_chat_service_account_json": json.dumps(SERVICE_ACCOUNT)}
ORDER = {"pedido": "EDR de la PoC", "clave_epica": " daia-250 ", "nuevo": False}


class Key(BaseModel):
    clave: str


class Harness:
    def __init__(self, properties: dict[str, str] | None = None):
        self.repository = FakeEdrRepository()
        self.writer = FakeEdrWriter('{"titulo": "PoC"}')
        self.jobs: list[Any] = []
        self.epics: list[str] = []
        self.google = Google()
        self.properties = Properties(dict(PROPERTIES if properties is None else properties))

        async def read_ticket(args: Key, context: ToolContext) -> str:
            self.epics.append(args.clave)
            return "épica"

        ticket = code_tool("leer_ticket", "Lee un ticket", Key, read_ticket)
        self.generate, self.read = edr_tools(ticket, lambda context: self.repository, lambda properties: self.writer,
                                             self.jobs.append, self.google.transport())

    def context(self, conversation: uuid.UUID | None = None, chat_key: str | None = "spaces/AAA/threads/T1") -> ToolContext:
        return ToolContext("jp@autofin.cl", self.properties, None, conversation or uuid.uuid4(), chat_key, "Arma el EDR")


async def call(tool: AreaTool, args: dict[str, Any], context: ToolContext) -> str:
    return await tool.run(args, context)


@pytest.fixture(autouse=True)
def clean_running():
    edr_module.RUNNING.clear()
    yield
    edr_module.RUNNING.clear()


@pytest.mark.anyio
async def test_generar_agenda_el_trabajo_y_responde_al_momento():
    harness = Harness()
    context = harness.context()

    reply = await call(harness.generate, ORDER, context)

    assert reply == STARTED and len(harness.jobs) == 1 and context.conversation_id in edr_module.RUNNING
    await harness.jobs[0]
    assert harness.epics == ["DAIA-250"] and "«PoC»" in harness.repository.replies[0]
    assert context.conversation_id not in edr_module.RUNNING
    assert "Persona: Arma el EDR" in str(harness.writer.calls[0][1].content)


@pytest.mark.anyio
async def test_un_segundo_pedido_espera_al_que_esta_en_curso():
    harness = Harness()
    context = harness.context()

    await call(harness.generate, ORDER, context)
    second = await call(harness.generate, ORDER, context)

    assert second == IN_PROGRESS and len(harness.jobs) == 1
    harness.jobs[0].close()


@pytest.mark.anyio
async def test_en_el_web_no_genera_ni_lee_el_edr():
    harness = Harness()
    context = harness.context(chat_key=None)

    assert await call(harness.generate, ORDER, context) == ONLY_GOOGLE_CHAT
    assert await call(harness.read, {}, context) == ONLY_GOOGLE_CHAT and harness.jobs == []


@pytest.mark.anyio
@pytest.mark.parametrize("properties", [{}, {**PROPERTIES, "edr_template_base64": "%%%"}])
async def test_sin_configuracion_no_agenda_ni_promete_un_enlace(properties):
    harness = Harness(properties)

    assert await call(harness.generate, ORDER, harness.context()) == NOT_CONFIGURED and harness.jobs == []


@pytest.mark.anyio
async def test_leer_entrega_titulo_enlace_y_pendientes_sin_generar():
    harness = Harness()
    context = harness.context()
    assert context.conversation_id is not None
    harness.repository.records[context.conversation_id] = [
        EdrRecord("doc-1", "https://docs.google.com/document/d/doc-1", "PoC", {"titulo": "PoC", "objetivo_general": "x"})]

    reply = await call(harness.read, {}, context)

    assert "Título: PoC" in reply and "https://docs.google.com/document/d/doc-1" in reply and "<informacion" in reply
    assert "visión general" in reply.split("Secciones pendientes:")[1] and harness.jobs == []


@pytest.mark.anyio
async def test_leer_sin_edr_dice_que_no_hay_o_que_esta_en_curso():
    harness = Harness()
    context = harness.context()

    assert await call(harness.read, {}, context) == NO_EDR
    await call(harness.generate, ORDER, context)
    assert await call(harness.read, {}, context) == IN_PROGRESS
    harness.jobs[0].close()


@pytest.mark.anyio
async def test_background_guarda_la_referencia_hasta_que_termina():
    done = asyncio.Event()

    async def job() -> None:
        done.set()

    edr_module.background(job())
    assert len(edr_module.TASKS) == 1
    await done.wait()
    await asyncio.sleep(0)
    assert edr_module.TASKS == set()


def test_el_esquema_de_generar_no_tiene_valores_por_defecto():
    harness = Harness()

    assert "default" not in json.dumps(harness.generate.parameters)
    assert set(harness.generate.parameters["required"]) == {"pedido", "clave_epica", "nuevo"}
