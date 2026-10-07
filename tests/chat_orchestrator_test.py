import logging
from datetime import UTC, datetime, time
from typing import cast
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents import strategies
from src.agents.graph import AgentContext, Catalog, build_graph
from src.agents.llm import AreaInfo, Classification, FaqHit, FinalText
from src.agents.retriever import ProcedureHit
from src.models.business_area import AreaScope
from src.models.procedure_field import FieldKind
from src.services.area_notifier import Requester
from src.services.procedures import FieldSpec
from src.models.official_channel import OfficialChannel
from src.models.web_session import WebPhase, WebSession
from src.services import chat_orchestrator
from src.services.chat_orchestrator import (
    INTERNAL_NOTIFICATION_FAILED, MIXED_SCOPE, UNAVAILABLE, handle_internal_message, handle_web_message)
from src.utils.exceptions.agent import LlmNotConfiguredError, LlmUnavailableError
from src.utils.exceptions.database import DatabaseUnavailableError
from tests.fakes import FakeAgentLLM, FakeClock, FakeNotifier, FakeRetriever, property_session, tool_call, web_session

SESSION = property_session({})
PAYROLL = AreaInfo(10, "Remuneraciones", "Sueldos", AreaScope.internal, "Eres Remuneraciones", "spaces/RRHH")
CREDITS = AreaInfo(1, "Créditos", "Créditos automotrices", AreaScope.external, "Eres Créditos", "spaces/CREDITOS")
HITS = {10: [FaqHit("¿Cuándo pagan?", "El día 30", 0.9)]}


class DownLLM(FakeAgentLLM):
    async def classify(self, prompt, question, areas, history) -> Classification:
        raise LlmUnavailableError("timeout")


async def load_catalog(scope: AreaScope) -> Catalog:
    return Catalog([PAYROLL, CREDITS], "Clasifica", "Eres el agente interno", "Reglas")


@pytest.fixture
def notifier(monkeypatch: pytest.MonkeyPatch) -> FakeNotifier:
    notifier = FakeNotifier()
    monkeypatch.setattr(chat_orchestrator, "AreaNotifier", lambda session_factory: notifier)
    return notifier


def use_llm(monkeypatch: pytest.MonkeyPatch, llm: FakeAgentLLM, hits=HITS):
    async def build_agent_context(session, requester):
        return AgentContext(llm, FakeRetriever(hits), load_catalog, FakeNotifier(), requester)

    monkeypatch.setattr(chat_orchestrator, "build_agent_context", build_agent_context)


ANA = Requester("Ana Pérez", "ana@autofin.cl", "google_chat")
INTERNAL_GRAPH = build_graph(AreaScope.internal)


async def ask(text: str = "¿Cuándo pagan el sueldo?", graph=INTERNAL_GRAPH, conversation_id: str = "spaces/AAA") -> str:
    return await handle_internal_message(SESSION, graph, text, ANA, conversation_id)


@pytest.mark.anyio
async def test_internal_respondida(monkeypatch: pytest.MonkeyPatch, notifier: FakeNotifier):
    use_llm(monkeypatch, FakeAgentLLM(area_ids=[10], answers={10: "El día 30"}))

    assert await ask() == "El día 30"
    assert notifier.sent == []


@pytest.mark.anyio
async def test_internal_mixta_pide_reformular(monkeypatch: pytest.MonkeyPatch, notifier: FakeNotifier):
    use_llm(monkeypatch, FakeAgentLLM(area_ids=[10, 1]))

    assert await ask() == MIXED_SCOPE


@pytest.mark.anyio
async def test_internal_sin_respuesta_avisa_al_responsable(monkeypatch: pytest.MonkeyPatch, notifier: FakeNotifier):
    use_llm(monkeypatch, FakeAgentLLM(area_ids=[10]), hits={})

    reply = await ask()

    assert "te contactará a la brevedad" in reply
    assert notifier.sent[0][0] == "spaces/RRHH"


@pytest.mark.anyio
async def test_internal_llm_no_configurado_responde_no_disponible(monkeypatch: pytest.MonkeyPatch, notifier: FakeNotifier):
    async def build_agent_context(session, requester):
        raise LlmNotConfiguredError("gemini_api_key")

    monkeypatch.setattr(chat_orchestrator, "build_agent_context", build_agent_context)

    assert await ask() == UNAVAILABLE


@pytest.mark.anyio
async def test_internal_llm_caido_responde_no_disponible(monkeypatch: pytest.MonkeyPatch, notifier: FakeNotifier):
    use_llm(monkeypatch, DownLLM())

    assert await ask() == UNAVAILABLE


# --- Canal web ---------------------------------------------------------------------------------------------------

EXTERNAL_HITS = {1: [FaqHit("¿Plazo?", "Hasta 48 meses", 0.9)], 2: [FaqHit("¿Cubre robo?", "Sí", 0.9)]}
INSURANCE = AreaInfo(2, "Seguros", "Seguros del vehículo", AreaScope.external, "Eres Seguros")
IN_HOURS = datetime(2026, 10, 7, 15, tzinfo=UTC)  # miércoles 12:00 en Santiago
OUT_OF_HOURS = datetime(2026, 10, 7, 23, tzinfo=UTC)


async def load_external_catalog(scope: AreaScope) -> Catalog:
    return Catalog([CREDITS, INSURANCE, PAYROLL], "Clasifica", "Eres el agente externo", "Reglas")


@pytest.fixture
def schedule(monkeypatch: pytest.MonkeyPatch):
    async def load_schedule(session):
        return {weekday: (time(9, 0), time(18, 0)) for weekday in range(5)}, set()

    async def get_official_channels(session):
        return [OfficialChannel(label="Teléfono", value="600 123 4567")]

    monkeypatch.setattr(strategies, "load_schedule", load_schedule)
    monkeypatch.setattr(strategies, "get_official_channels", get_official_channels)
    monkeypatch.setattr(chat_orchestrator, "get_official_channels", get_official_channels)


CONTRACT = ProcedureHit(7, "Copia del contrato", "El área envía la copia", [FieldSpec("rut", "RUT del titular", FieldKind.rut)], 0.9)
PROCEDURES = {1: [CONTRACT]}
LOAD = ProcedureHit(9, "Cargar documento", "Gestión lo carga", [FieldSpec("documento", "Número de documento", FieldKind.number)], 0.9)


def use_external_llm(monkeypatch: pytest.MonkeyPatch, llm: FakeAgentLLM, notifier_for_tools: FakeNotifier | None = None):
    notifier_for_tools = notifier_for_tools or FakeNotifier()

    async def build_agent_context(session, requester):
        return AgentContext(llm, FakeRetriever(EXTERNAL_HITS, PROCEDURES), load_external_catalog, notifier_for_tools, requester)

    monkeypatch.setattr(chat_orchestrator, "build_agent_context", build_agent_context)


async def ask_web(session: WebSession, text: str = "¿Cuál es el plazo?", now: datetime = IN_HOURS) -> list:
    graph = build_graph(AreaScope.external, InMemorySaver())
    return await handle_web_message(property_session({}), graph, session, text, FakeClock(now))


def dumps(messages: list) -> list[dict]:
    return [message.model_dump(by_alias=True, exclude_none=True) for message in messages]


@pytest.mark.anyio
async def test_web_respondida(monkeypatch: pytest.MonkeyPatch, schedule):
    use_external_llm(monkeypatch, FakeAgentLLM(area_ids=[1], answers={1: "Hasta 48 meses"}))

    assert dumps(await ask_web(web_session())) == [{"type": "message", "from": "bot", "text": "Hasta 48 meses"}]


@pytest.mark.anyio
async def test_web_parcial(monkeypatch: pytest.MonkeyPatch, schedule):
    use_external_llm(monkeypatch, FakeAgentLLM(area_ids=[1, 2], answers={1: "Hasta 48 meses", 2: None}, combined="Solo plazo"))

    assert dumps(await ask_web(web_session())) == [{"type": "message", "from": "bot", "text": "Solo plazo"}]


@pytest.mark.anyio
async def test_web_mixta_pide_reformular(monkeypatch: pytest.MonkeyPatch, schedule):
    use_external_llm(monkeypatch, FakeAgentLLM(area_ids=[1, 10]))

    assert dumps(await ask_web(web_session())) == [{"type": "message", "from": "bot", "text": MIXED_SCOPE}]


@pytest.mark.anyio
async def test_web_sin_respuesta_dentro_de_horario_ofrece_un_ejecutivo(monkeypatch: pytest.MonkeyPatch, schedule):
    use_external_llm(monkeypatch, FakeAgentLLM(area_ids=[]))
    session = web_session()

    messages = dumps(await ask_web(session, "¿Puedo pagar con cheque?"))

    assert [m["type"] for m in messages] == ["message", "offer_human"]
    assert session.phase == WebPhase.offering_human
    assert session.pending_question == "¿Puedo pagar con cheque?"


@pytest.mark.anyio
async def test_web_sin_respuesta_fuera_de_horario_muestra_canales(monkeypatch: pytest.MonkeyPatch, schedule):
    use_external_llm(monkeypatch, FakeAgentLLM(area_ids=[]))

    messages = dumps(await ask_web(web_session(), now=OUT_OF_HOURS))

    assert [m["type"] for m in messages] == ["message", "official_channels"]
    assert messages[1]["channels"] == [{"label": "Teléfono", "value": "600 123 4567"}]


@pytest.mark.anyio
async def test_web_peticion_de_humano_ofrece_un_ejecutivo(monkeypatch: pytest.MonkeyPatch, schedule):
    use_external_llm(monkeypatch, FakeAgentLLM(wants_human=True))

    assert [m["type"] for m in dumps(await ask_web(web_session(), "Quiero hablar con una persona"))] == ["message", "offer_human"]


@pytest.mark.anyio
async def test_web_llm_caido_responde_no_disponible(monkeypatch: pytest.MonkeyPatch, schedule):
    use_external_llm(monkeypatch, DownLLM())

    assert dumps(await ask_web(web_session())) == [{"type": "error", "code": "service_unavailable", "text": UNAVAILABLE}]


@pytest.mark.anyio
async def test_web_bd_caida_responde_no_disponible_y_lo_registra(
    monkeypatch: pytest.MonkeyPatch, schedule, caplog: pytest.LogCaptureFixture
):
    async def build_agent_context(session, requester):
        raise DatabaseUnavailableError("conexión rechazada")

    monkeypatch.setattr(chat_orchestrator, "build_agent_context", build_agent_context)
    caplog.set_level(logging.ERROR)

    assert dumps(await ask_web(web_session())) == [{"type": "error", "code": "service_unavailable", "text": UNAVAILABLE}]
    assert "conexión rechazada" in caplog.text


class CountingSession:
    def __init__(self):
        self.commits = 0

    async def execute(self, statement):
        return []

    async def scalar(self, statement):
        return None

    async def commit(self):
        self.commits += 1


class CommitAwareLLM(FakeAgentLLM):
    def __init__(self, session: CountingSession):
        super().__init__(area_ids=[1], answers={1: "Hasta 48 meses"})
        self.session = session
        self.commits_at_classify = -1

    async def classify(self, prompt, question, areas, history) -> Classification:
        self.commits_at_classify = self.session.commits
        return await super().classify(prompt, question, areas, history)


@pytest.mark.anyio
async def test_web_libera_la_conexion_antes_de_llamar_al_modelo(monkeypatch: pytest.MonkeyPatch, schedule):
    # Con 50 sesiones a la vez, retener la conexión durante la llamada al modelo agota el pool de la BD.
    session = CountingSession()
    llm = CommitAwareLLM(session)
    use_external_llm(monkeypatch, llm)

    graph = build_graph(AreaScope.external, InMemorySaver())
    await handle_web_message(cast(AsyncSession, session), graph, web_session(), "¿Plazo?", FakeClock(IN_HOURS))

    assert llm.commits_at_classify >= 1


@pytest.mark.anyio
async def test_internal_libera_la_conexion_antes_de_llamar_al_modelo(monkeypatch: pytest.MonkeyPatch, notifier: FakeNotifier):
    session = CountingSession()
    llm = CommitAwareLLM(session)
    use_llm(monkeypatch, llm)

    await handle_internal_message(cast(AsyncSession, session), INTERNAL_GRAPH, "¿Cuándo pagan?", ANA, "spaces/AAA")

    assert llm.commits_at_classify >= 1



# --- Ampliación: identidad, notificación fallida y derivación ----------------------------------------------------

@pytest.mark.anyio
async def test_requester_cada_canal_pasa_su_identidad(monkeypatch: pytest.MonkeyPatch, notifier: FakeNotifier, schedule):
    seen: list[Requester | None] = []
    llm = FakeAgentLLM(area_ids=[1], answers={1: "Hasta 48 meses"})

    async def build_agent_context(session, requester):
        seen.append(requester)
        return AgentContext(llm, FakeRetriever(EXTERNAL_HITS), load_external_catalog, FakeNotifier(), requester)

    monkeypatch.setattr(chat_orchestrator, "build_agent_context", build_agent_context)
    await ask()
    await ask_web(web_session())

    assert seen == [Requester("Ana Pérez", "ana@autofin.cl", "google_chat"), None]


RUT_OK = [{"campo": "rut", "valor": "12.345.678-5"}, {"campo": "nombre", "valor": "Ana"}, {"campo": "contacto", "valor": "ana@correo.cl"}]


@pytest.mark.anyio
async def test_web_notification_fallida_muestra_los_canales_oficiales(monkeypatch: pytest.MonkeyPatch, schedule):
    llm = FakeAgentLLM(area_ids=[1], steps={"Créditos": [tool_call("notificar_area", procedimiento_id=7, datos=RUT_OK)]})
    use_external_llm(monkeypatch, llm, FakeNotifier(fail=True))

    messages = dumps(await ask_web(web_session(), "Quiero copia de mi contrato"))

    assert [m["type"] for m in messages] == ["message", "official_channels"]


@pytest.mark.anyio
async def test_web_derivar_desde_el_sub_agente_ofrece_un_ejecutivo(monkeypatch: pytest.MonkeyPatch, schedule):
    use_external_llm(monkeypatch, FakeAgentLLM(area_ids=[1], steps={"Créditos": [tool_call("derivar_a_ejecutivo")]}))

    assert [m["type"] for m in dumps(await ask_web(web_session()))] == ["message", "offer_human"]


@pytest.mark.anyio
async def test_web_procedimiento_notificado_confirma_al_cliente(monkeypatch: pytest.MonkeyPatch, schedule):
    use_external_llm(monkeypatch, FakeAgentLLM(area_ids=[1], steps={"Créditos": [
        tool_call("notificar_area", procedimiento_id=7, datos=RUT_OK), FinalText("Listo, el área gestionará tu solicitud.")]}))

    messages = dumps(await ask_web(web_session(), "Quiero copia de mi contrato"))

    assert messages == [{"type": "message", "from": "bot", "text": "Listo, el área gestionará tu solicitud."}]



# --- Memoria del canal interno -----------------------------------------------------------------------------------

@pytest.mark.anyio
async def test_internal_thread_recuerda_la_conversacion_y_aisla_otros_hilos(monkeypatch: pytest.MonkeyPatch, notifier: FakeNotifier):
    llm = FakeAgentLLM(area_ids=[10], answers={10: "El día 30"})
    use_llm(monkeypatch, llm)
    graph = build_graph(AreaScope.internal, InMemorySaver())

    await ask("¿Cuándo pagan?", graph, "spaces/AAA/threads/T1")
    await ask("¿Y el bono?", graph, "spaces/AAA/threads/T1")
    await ask("Hola", graph, "spaces/AAA/threads/T2")

    assert [str(m.content) for m in llm.histories[1]] == ["¿Cuándo pagan?", "El día 30"]
    assert llm.histories[2] == []


@pytest.mark.anyio
async def test_internal_notification_fallida_pide_contactar_al_area(monkeypatch: pytest.MonkeyPatch, notifier: FakeNotifier):
    llm = FakeAgentLLM(area_ids=[10], steps={"Remuneraciones": [
        tool_call("notificar_area", procedimiento_id=9, datos=[{"campo": "documento", "valor": "123"}])]})

    async def build_agent_context(session, requester):
        return AgentContext(llm, FakeRetriever(HITS, {10: [LOAD]}), load_catalog, FakeNotifier(fail=True), requester)

    monkeypatch.setattr(chat_orchestrator, "build_agent_context", build_agent_context)

    assert await ask("Carga el documento 123") == INTERNAL_NOTIFICATION_FAILED


class StatementSession(CountingSession):
    def __init__(self):
        super().__init__()
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return []


@pytest.mark.anyio
async def test_internal_registra_la_actividad_en_chat_thread(monkeypatch: pytest.MonkeyPatch, notifier: FakeNotifier):
    use_llm(monkeypatch, FakeAgentLLM(area_ids=[10], answers={10: "El día 30"}))
    session = StatementSession()

    await handle_internal_message(cast(AsyncSession, session), INTERNAL_GRAPH, "¿Cuándo pagan?", ANA, "spaces/AAA/threads/T1")

    upsert = next(statement for statement in session.statements if "chat_thread" in str(statement))
    compiled = upsert.compile(dialect=postgresql.dialect())
    assert "INSERT INTO chat_thread" in str(compiled)
    assert "ON CONFLICT (conversation_id) DO UPDATE SET last_message_at" in str(compiled)
    assert compiled.params["conversation_id"] == "spaces/AAA/threads/T1"
