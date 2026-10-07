import logging
from datetime import UTC, datetime, time
from typing import cast
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents import strategies
from src.agents.graph import AgentContext, Catalog, build_graph
from src.agents.llm import AreaInfo, Classification, FaqHit
from src.models.business_area import AreaScope
from src.models.official_channel import OfficialChannel
from src.models.web_session import WebPhase, WebSession
from src.services import chat_orchestrator
from src.services.chat_orchestrator import MIXED_SCOPE, UNAVAILABLE, handle_internal_message, handle_web_message
from src.utils.exceptions.agent import LlmNotConfiguredError, LlmUnavailableError
from src.utils.exceptions.database import DatabaseUnavailableError
from tests.fakes import FakeAgentLLM, FakeClock, FakeMailer, FakeRetriever, property_session, web_session

SESSION = cast(AsyncSession, object())
PAYROLL = AreaInfo(10, "Remuneraciones", "Sueldos", AreaScope.internal, "Eres Remuneraciones", "rrhh@autofin.cl")
CREDITS = AreaInfo(1, "Créditos", "Créditos automotrices", AreaScope.external, "Eres Créditos")
HITS = {10: [FaqHit("¿Cuándo pagan?", "El día 30", 0.9)]}


class DownLLM(FakeAgentLLM):
    async def classify(self, prompt, question, areas, history) -> Classification:
        raise LlmUnavailableError("timeout")


async def load_catalog(scope: AreaScope) -> Catalog:
    return Catalog([PAYROLL, CREDITS], "Clasifica", "Eres el agente interno")


@pytest.fixture
def mailer(monkeypatch: pytest.MonkeyPatch) -> FakeMailer:
    mailer = FakeMailer()
    monkeypatch.setattr(chat_orchestrator, "Mailer", lambda session: mailer)
    return mailer


def use_llm(monkeypatch: pytest.MonkeyPatch, llm: FakeAgentLLM, hits=HITS):
    async def build_agent_context(session):
        return AgentContext(llm, FakeRetriever(hits), load_catalog)

    monkeypatch.setattr(chat_orchestrator, "build_agent_context", build_agent_context)


async def ask(text: str = "¿Cuándo pagan el sueldo?") -> str:
    return await handle_internal_message(SESSION, text, "Ana Pérez", "ana@autofin.cl")


@pytest.mark.anyio
async def test_internal_respondida(monkeypatch: pytest.MonkeyPatch, mailer: FakeMailer):
    use_llm(monkeypatch, FakeAgentLLM(area_ids=[10], answers={10: "El día 30"}))

    assert await ask() == "El día 30"
    assert mailer.sent == []


@pytest.mark.anyio
async def test_internal_mixta_pide_reformular(monkeypatch: pytest.MonkeyPatch, mailer: FakeMailer):
    use_llm(monkeypatch, FakeAgentLLM(area_ids=[10, 1]))

    assert await ask() == MIXED_SCOPE


@pytest.mark.anyio
async def test_internal_sin_respuesta_avisa_al_responsable(monkeypatch: pytest.MonkeyPatch, mailer: FakeMailer):
    use_llm(monkeypatch, FakeAgentLLM(area_ids=[10]), hits={})

    reply = await ask()

    assert "te contactará a la brevedad" in reply
    assert mailer.sent[0][0] == ["rrhh@autofin.cl"]


@pytest.mark.anyio
async def test_internal_llm_no_configurado_responde_no_disponible(monkeypatch: pytest.MonkeyPatch, mailer: FakeMailer):
    async def build_agent_context(session):
        raise LlmNotConfiguredError("gemini_api_key")

    monkeypatch.setattr(chat_orchestrator, "build_agent_context", build_agent_context)

    assert await ask() == UNAVAILABLE


@pytest.mark.anyio
async def test_internal_llm_caido_responde_no_disponible(monkeypatch: pytest.MonkeyPatch, mailer: FakeMailer):
    use_llm(monkeypatch, DownLLM())

    assert await ask() == UNAVAILABLE


# --- Canal web ---------------------------------------------------------------------------------------------------

EXTERNAL_HITS = {1: [FaqHit("¿Plazo?", "Hasta 48 meses", 0.9)], 2: [FaqHit("¿Cubre robo?", "Sí", 0.9)]}
INSURANCE = AreaInfo(2, "Seguros", "Seguros del vehículo", AreaScope.external, "Eres Seguros")
IN_HOURS = datetime(2026, 10, 7, 15, tzinfo=UTC)  # miércoles 12:00 en Santiago
OUT_OF_HOURS = datetime(2026, 10, 7, 23, tzinfo=UTC)


async def load_external_catalog(scope: AreaScope) -> Catalog:
    return Catalog([CREDITS, INSURANCE, PAYROLL], "Clasifica", "Eres el agente externo")


@pytest.fixture
def schedule(monkeypatch: pytest.MonkeyPatch):
    async def load_schedule(session):
        return {weekday: (time(9, 0), time(18, 0)) for weekday in range(5)}, set()

    async def get_official_channels(session):
        return [OfficialChannel(label="Teléfono", value="600 123 4567")]

    monkeypatch.setattr(strategies, "load_schedule", load_schedule)
    monkeypatch.setattr(strategies, "get_official_channels", get_official_channels)


def use_external_llm(monkeypatch: pytest.MonkeyPatch, llm: FakeAgentLLM):
    async def build_agent_context(session):
        return AgentContext(llm, FakeRetriever(EXTERNAL_HITS), load_external_catalog)

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
    async def build_agent_context(session):
        raise DatabaseUnavailableError("conexión rechazada")

    monkeypatch.setattr(chat_orchestrator, "build_agent_context", build_agent_context)
    caplog.set_level(logging.ERROR)

    assert dumps(await ask_web(web_session())) == [{"type": "error", "code": "service_unavailable", "text": UNAVAILABLE}]
    assert "conexión rechazada" in caplog.text
