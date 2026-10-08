import logging
from typing import cast
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from src.agents.llm import (
    AgentLLM, AreaInfo, AreaSection, FaqHit, FinalText, GeminiAgentLLM, ToolCall, ToolCalls, ToolSpec,
    build_area_messages, build_gemini_llm, build_scope_messages, gemini_chat)
from src.agents.retriever import ProcedureHit
from src.models.business_area import AreaScope
from src.models.procedure_field import FieldKind
from src.services.procedures import FieldSpec
from src.utils.exceptions.agent import LlmNotConfiguredError, LlmUnavailableError
from src.agents.llm import CallBudget, ScopeDecision, ScopeOutput, build_coordinator_messages
from src.services.business_data import AreaTopics
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

    messages = build_scope_messages("Prompt", [], None, history, "q4", 3)

    assert [str(m.content) for m in messages[1:]] == ["q3", "a3", "q4"]


INSURANCE = AreaInfo(2, "Seguros", "Seguros automotrices", AreaScope.external, "Eres el área de Seguros")


def test_coordinator_messages_nombran_las_areas_sin_su_contenido():
    messages = build_scope_messages("Prompt del canal", [CREDITS, INSURANCE], None, [], "¿Plazo?", 20)
    system = str(messages[0].content)

    assert system.startswith("Prompt del canal")
    assert "[A1] Créditos: Créditos automotrices" in system and "[A2] Seguros: Seguros automotrices" in system
    assert "Eres el área de" not in system and "Hasta 48 meses" not in system
    assert "Procedimiento en curso" not in system
    assert str(messages[-1].content) == "¿Plazo?"


def test_scope_messages_con_procedimiento_en_curso():
    pending = ProcedureHit(7, "Copia del contrato", "Se envía", [], 1.0, 1)

    system = str(build_scope_messages("Prompt", [CREDITS], pending, [], "12.345.678-5", 20)[0].content)

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


def test_area_messages_piden_contenido_para_el_coordinador_sin_persona():
    messages = build_area_messages(CREDITS, "Reglas", SECTION.faqs, [], None, [], "¿Plazo?", 20, [])
    system = str(messages[0].content)

    assert "coordinador" in system and "no hablas con el usuario" in system
    assert "Persona del asistente" not in system


def test_gemini_chat_temperature_forma_parte_de_la_clave():
    cold = gemini_chat("gemini-flash", API_KEY, 20, 0.0)
    warm = gemini_chat("gemini-flash", API_KEY, 20, 0.7)

    assert cold is not warm
    assert (cold.temperature, warm.temperature) == (0.0, 0.7)
    assert gemini_chat("gemini-flash", API_KEY, 20, 0.7) is warm


@pytest.mark.anyio
@pytest.mark.parametrize(("kwargs", "expected"), [({}, 0.0), ({"temperature": 0.7}, 0.7)])
async def test_build_gemini_llm_temperature_llega_al_cliente(kwargs, expected):
    session = property_session({"gemini_model": "gemini-flash", "gemini_api_key": API_KEY})

    llm = await build_gemini_llm(session, **kwargs)

    assert cast(ChatGoogleGenerativeAI, llm._chat).temperature == expected



# --- Spec 004: agente de ámbito, dobles y presupuesto ---------------------------------------------------------------

def test_scope_messages_incluyen_los_temas_de_cada_area_sin_contenido():
    topics = {1: AreaTopics(["¿Plazo máximo?", "¿Tasa de interés?"], ["Copia del contrato"])}

    system = str(build_scope_messages("Prompt del ámbito", [CREDITS], None, [], "¿y el plazo?", 20, topics)[0].content)

    assert "[A1] Créditos" in system and "¿Plazo máximo?; ¿Tasa de interés?" in system and "Copia del contrato" in system
    assert "Hasta 48 meses" not in system


def test_scope_messages_sin_temas_no_cambian():
    without = build_scope_messages("Prompt", [CREDITS], None, [], "hola", 20)
    empty = build_scope_messages("Prompt", [CREDITS], None, [], "hola", 20, {})

    assert [m.content for m in empty] == [m.content for m in without]


@pytest.mark.anyio
async def test_decide_scope_traduce_la_salida():
    output = ScopeOutput(area_ids=[1, 2], consulta="¿Plazo del crédito?", catalogo=False)

    decision = await GeminiAgentLLM(cast(BaseChatModel, StructuredChat(output))).decide_scope([HumanMessage("¿plazo?")])

    assert decision == ScopeDecision([1, 2], "¿Plazo del crédito?", False)


@pytest.mark.anyio
async def test_decide_scope_error_del_proveedor_es_llm_no_disponible():
    with pytest.raises(LlmUnavailableError):
        await GeminiAgentLLM(cast(BaseChatModel, StructuredChat(error=RuntimeError("x")))).decide_scope([HumanMessage("a")])


def test_decide_scope_describe_el_catalogo():
    description = ScopeOutput.model_json_schema()["properties"]["catalogo"]["description"]

    assert "qué puede consultar" in description


@pytest.mark.anyio
async def test_fake_decide_scope_guionizado_y_por_defecto():
    scripted = FakeAgentLLM(scope=[ScopeDecision([2], "¿Robo?", False)])

    assert await scripted.decide_scope([HumanMessage("¿robo?")]) == ScopeDecision([2], "¿Robo?", False)
    assert await FakeAgentLLM().decide_scope([HumanMessage("¿plazo?")]) == ScopeDecision([], "¿plazo?", False)
    assert (scripted.scope_calls, scripted.calls) == (1, 1)


@pytest.mark.anyio
async def test_fake_coordinador_por_defecto_consulta_y_retransmite():
    llm = FakeAgentLLM()
    first = await llm.step([SystemMessage("Coordinador"), HumanMessage("¿Plazo?")], [])
    final = await llm.step([SystemMessage("Coordinador"), HumanMessage("¿Plazo?"),
                            ToolMessage("[Créditos]\nHasta 48 meses", tool_call_id="c1")], [])

    assert isinstance(first, ToolCalls) and first.calls[0].name == "consultar_areas"
    assert first.calls[0].args == {"consulta": "¿Plazo?"}
    assert final == FinalText("Hasta 48 meses")
    assert llm.coordinator_step_calls == 2


@pytest.mark.anyio
async def test_fake_coordinador_guionizado():
    llm = FakeAgentLLM(coordinator_steps=[FinalText("¡Hola! ¿En qué te ayudo?")])

    assert await llm.step([SystemMessage("Coordinador"), HumanMessage("hola")], []) == FinalText("¡Hola! ¿En qué te ayudo?")


def test_presupuesto_permite_hasta_el_tope(caplog: pytest.LogCaptureFixture):
    budget = CallBudget(2)
    budget.spend()
    budget.spend()

    with pytest.raises(LlmUnavailableError):
        budget.spend()
    assert "presupuesto" in caplog.text and budget.used == 2



def test_coordinador_mensajes_sin_areas_ni_contenido():
    history = [HumanMessage("¿Cuándo pagan?"), AIMessage("El día 30.")]

    messages = build_coordinator_messages("Prompt del coordinador", "Tono cercano.", False, None, history, "¿y el bono?", 20)
    system = str(messages[0].content)

    assert "Prompt del coordinador" in system and "Tono cercano." in system and "español" in system
    assert "Áreas del canal" not in system and "[A" not in system
    assert [str(m.content) for m in messages[1:]] == ["¿Cuándo pagan?", "El día 30.", "¿y el bono?"]


def test_coordinador_mensajes_con_oferta_y_tramite_en_curso():
    system = str(build_coordinator_messages("Prompt", None, True, "Copia del contrato", [], "sí", 20)[0].content)

    assert "oferta" in system and "«Copia del contrato»" in system and "Persona" not in system



# --- Spec 005: transcripción de imágenes y PDF ----------------------------------------------------------------------

class CapturingChat:
    def __init__(self, text: str = "", error: Exception | None = None):
        self.text = text
        self.error = error
        self.messages: list = []

    async def ainvoke(self, messages):
        self.messages = messages
        if self.error:
            raise self.error
        return AIMessage(self.text)


@pytest.mark.anyio
@pytest.mark.parametrize(("mime_type", "block_type"), [("image/png", "image"), ("application/pdf", "file")])
async def test_transcribe_envia_el_archivo_como_bloque_multimodal(mime_type, block_type):
    chat = CapturingChat("Captura de un error 500 en el portal")

    text = await GeminiAgentLLM(cast(BaseChatModel, chat)).transcribe(b"%bytes%", mime_type)

    assert text == "Captura de un error 500 en el portal"
    instruction, media = chat.messages[0].content
    assert instruction["type"] == "text" and "transcribe" in instruction["text"].lower()
    assert (media["type"], media["base64"], media["mime_type"]) == (block_type, "JWJ5dGVzJQ==", mime_type)


@pytest.mark.anyio
async def test_transcribe_error_del_proveedor_es_llm_no_disponible():
    chat = CapturingChat(error=RuntimeError("timeout"))

    with pytest.raises(LlmUnavailableError):
        await GeminiAgentLLM(cast(BaseChatModel, chat)).transcribe(b"x", "image/png")


@pytest.mark.anyio
async def test_fake_transcribe_guionizado_y_por_defecto():
    llm = FakeAgentLLM(transcripts=["Texto del PDF"])

    assert await llm.transcribe(b"x", "application/pdf") == "Texto del PDF"
    assert await FakeAgentLLM().transcribe(b"x", "image/png") == ""
    assert llm.transcribe_calls == 1
