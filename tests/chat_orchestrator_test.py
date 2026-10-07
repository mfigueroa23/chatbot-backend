from typing import cast
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.graph import AgentContext, Catalog
from src.agents.llm import AreaInfo, Classification, FaqHit
from src.models.business_area import AreaScope
from src.services import chat_orchestrator
from src.services.chat_orchestrator import MIXED_SCOPE, UNAVAILABLE, handle_internal_message
from src.utils.exceptions.agent import LlmNotConfiguredError, LlmUnavailableError
from tests.fakes import FakeAgentLLM, FakeMailer, FakeRetriever

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
