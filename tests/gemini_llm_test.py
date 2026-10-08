import logging
from typing import cast
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from src.agents.behavior import ClarifyOption
from src.agents.llm import (
    AgentLLM, AreaInfo, AreaSection, CoordinatorOutput, CoordinatorReply, FaqHit, FinalText, GeminiAgentLLM, ToolCall,
    ToolCalls, ToolSpec, build_area_messages, build_coordinator_messages, build_gemini_llm)
from src.agents.retriever import ProcedureHit
from src.models.business_area import AreaScope
from src.models.procedure_field import FieldKind
from src.services.procedures import FieldSpec
from src.utils.exceptions.agent import LlmNotConfiguredError, LlmUnavailableError
from tests.fakes import FakeAgentLLM, property_session

API_KEY = "clave-secreta-de-prueba"


class StructuredChat:
    def __init__(self, output=None, error: Exception | None = None):
        self.output = output
        self.error = error

    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, messages):
        if self.error:
            raise self.error
        return self.output


def test_fake_agent_llm_cumple_la_interfaz():
    llm: AgentLLM = FakeAgentLLM()

    assert isinstance(llm, FakeAgentLLM)


@pytest.mark.anyio
async def test_sin_api_key_lanza_llm_no_configurado():
    with pytest.raises(LlmNotConfiguredError):
        await build_gemini_llm(property_session({"gemini_model": "gemini-flash"}))


@pytest.mark.anyio
async def test_sin_modelo_lanza_llm_no_configurado_sin_registrar_la_clave(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG)

    with pytest.raises(LlmNotConfiguredError):
        await build_gemini_llm(property_session({"gemini_api_key": API_KEY}))

    assert "gemini_model" in caplog.text
    assert API_KEY not in caplog.text


CREDITS = AreaInfo(1, "Créditos", "Créditos automotrices", AreaScope.external, "Eres el área de Créditos")
SECTION = AreaSection(CREDITS, [FaqHit("¿Plazo?", "Hasta 48 meses", 0.9, id=11, area_id=1)],
                      [ProcedureHit(7, "Copia del contrato", "Se envía al correo", [FieldSpec("rut", "RUT del titular", FieldKind.rut)], 0.9, 1)])


def test_coordinator_messages_cortan_el_historial_en_un_mensaje_del_usuario():
    history = [HumanMessage("q1"), AIMessage("a1"), HumanMessage("q2"), AIMessage("a2"), HumanMessage("q3"), AIMessage("a3")]

    messages = build_coordinator_messages("Prompt", [], [], False, None, history, "q4", 3)

    assert [str(m.content) for m in messages[1:]] == ["q3", "a3", "q4"]


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["delegate", "no_answer", "greeting", "closing", "off_topic", "manipulation",
                                  "wants_human", "accept_offer", "decline_offer", "choice"])
async def test_coordinate_traduce_cada_kind(kind):
    output = CoordinatorOutput(kind=kind, area_ids=[1, 2], chosen_options=[3])

    reply = await GeminiAgentLLM(cast(BaseChatModel, StructuredChat(output))).coordinate([HumanMessage("hola")])

    assert reply == CoordinatorReply(kind, [1, 2], [3])


@pytest.mark.anyio
async def test_coordinate_error_del_proveedor_es_llm_no_disponible():
    with pytest.raises(LlmUnavailableError):
        await GeminiAgentLLM(cast(BaseChatModel, StructuredChat(error=TimeoutError("timeout")))).coordinate([])


def test_coordinate_describe_las_reglas_de_la_spec():
    description = CoordinatorOutput.model_json_schema()["properties"]["kind"]["description"]

    for rule in ("solo un saludo", "número", "paráfrasis", "oferta"):
        assert rule in description


INSURANCE = AreaInfo(2, "Seguros", "Seguros automotrices", AreaScope.external, "Eres el área de Seguros")
OPTIONS = [ClarifyOption(1, "faq", 11, 1, "¿Plazo del crédito?"), ClarifyOption(2, "procedure", 7, 1, "Copia del contrato")]


def test_coordinator_messages_nombran_las_areas_sin_su_contenido():
    messages = build_coordinator_messages("Prompt del canal", [CREDITS, INSURANCE], [], False, None, [], "¿Plazo?", 20)
    system = str(messages[0].content)

    assert system.startswith("Prompt del canal")
    assert "[A1] Créditos: Créditos automotrices" in system and "[A2] Seguros: Seguros automotrices" in system
    assert "Eres el área de" not in system and "Hasta 48 meses" not in system
    assert "Opciones ofrecidas" not in system and "ejecutivo" not in system and "Procedimiento en curso" not in system
    assert str(messages[-1].content) == "¿Plazo?"


def test_coordinator_messages_con_opciones_oferta_y_procedimiento_en_curso():
    pending = ProcedureHit(7, "Copia del contrato", "Se envía", [], 1.0, 1)

    system = str(build_coordinator_messages("Prompt", [CREDITS], OPTIONS, True, pending, [], "la 2", 20)[0].content)

    assert "Opciones ofrecidas al usuario" in system and "1. ¿Plazo del crédito?" in system and "2. Copia del contrato" in system
    assert "oferta de hablar con un ejecutivo" in system
    assert "Procedimiento en curso: Copia del contrato [A1]" in system
    assert "Se envía" not in system


class ToolChat:
    def __init__(self, message: AIMessage | None = None, error: Exception | None = None):
        self.message = message
        self.error = error
        self.tools: list = []

    def bind_tools(self, tools):
        self.tools = tools
        return self

    async def ainvoke(self, messages):
        if self.error:
            raise self.error
        return self.message


SEARCH = ToolSpec("buscar_faq", "Busca preguntas frecuentes del área", {"type": "object", "properties": {}})


@pytest.mark.anyio
async def test_step_devuelve_las_llamadas_a_tools():
    chat = ToolChat(AIMessage("", tool_calls=[{"id": "c1", "name": "buscar_faq", "args": {"consulta": "plazo"}}]))

    step = await GeminiAgentLLM(cast(BaseChatModel, chat)).step([HumanMessage("¿Plazo?")], [SEARCH])

    assert step == ToolCalls([ToolCall("c1", "buscar_faq", {"consulta": "plazo"})])
    assert chat.tools[0]["name"] == "buscar_faq"


@pytest.mark.anyio
async def test_step_devuelve_el_texto_final():
    step = await GeminiAgentLLM(cast(BaseChatModel, ToolChat(AIMessage("Hasta 48 meses")))).step([], [SEARCH])

    assert step == FinalText("Hasta 48 meses")


@pytest.mark.anyio
async def test_step_error_del_proveedor_es_llm_no_disponible():
    with pytest.raises(LlmUnavailableError):
        await GeminiAgentLLM(cast(BaseChatModel, ToolChat(error=TimeoutError("timeout")))).step([], [SEARCH])


def test_area_messages_solo_incluyen_su_area_y_piden_espanol():
    pending = ProcedureHit(7, "Copia del contrato", "Se envía", [], 1.0, 1)

    messages = build_area_messages(CREDITS, "Reglas", SECTION.faqs, SECTION.procedures, pending, [], "¿Plazo?", 20, [])
    system = str(messages[0].content)

    assert "Eres el área de Créditos" in system and "Reglas" in system and "[F11]" in system and "[P7]" in system
    assert "Procedimiento en curso" in system and "español" in system
    assert "Seguros" not in system
    assert str(messages[-1].content) == "¿Plazo?"
