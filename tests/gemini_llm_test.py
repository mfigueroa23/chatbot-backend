import logging
from typing import cast
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from src.agents.llm import (
    AgentLLM, AreaAnswer, AreaInfo, FaqHit, FinalText, GeminiAgentLLM, ToolCall, ToolCalls, ToolSpec, build_answer_messages,
    build_area_messages, build_combine_messages, build_gemini_llm)
from src.models.business_area import AreaScope
from src.utils.exceptions.agent import LlmNotConfiguredError, LlmUnavailableError
from tests.fakes import FakeAgentLLM, property_session

API_KEY = "clave-secreta-de-prueba"


class FailingChat:
    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, messages):
        raise TimeoutError("tiempo de espera agotado")


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


@pytest.mark.anyio
async def test_error_del_proveedor_se_convierte_en_llm_no_disponible():
    llm = GeminiAgentLLM(cast(BaseChatModel, FailingChat()))

    with pytest.raises(LlmUnavailableError):
        await llm.classify("Clasifica", "¿Plazo del crédito?", [], [])


def test_la_respuesta_de_un_area_solo_incluye_su_prompt_y_sus_faq():
    area = AreaInfo(1, "Créditos", "Créditos automotrices", AreaScope.external, "Eres el área de Créditos")
    faqs = [FaqHit("¿Cuál es el plazo máximo?", "Hasta 48 meses", 0.9)]

    messages = build_answer_messages(area, "Reglas comunes desde la BD", "¿Cuántos meses puedo pagar?", faqs, [])
    content = "\n".join(str(message.content) for message in messages)

    assert "Eres el área de Créditos" in content
    assert "Reglas comunes desde la BD" in content
    assert "¿Cuál es el plazo máximo?" in content and "Hasta 48 meses" in content
    assert "Cobranza" not in content
    assert content.count("Respuesta:") == 1


def test_las_instrucciones_de_combinar_vienen_solo_del_prompt_del_agente():
    parts = [AreaAnswer(1, "Créditos", "Hasta 48 meses"), AreaAnswer(2, "Seguros", None)]

    system, user = build_combine_messages("Prompt del agente desde la BD", "¿Plazo y seguro?", parts)

    assert system.content == "Prompt del agente desde la BD"
    assert "Créditos: Hasta 48 meses" in str(user.content) and "Seguros" in str(user.content)


# --- step con tools -----------------------------------------------------------------------------------------------

class ToolChat:
    def __init__(self, reply=None, error: Exception | None = None):
        self.reply = reply
        self.error = error
        self.bound_tools: list = []

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    async def ainvoke(self, messages):
        if self.error:
            raise self.error
        return self.reply


TOOLS = [ToolSpec("buscar_faq", "Busca en las FAQ del área", {"type": "object", "properties": {"consulta": {"type": "string"}}})]


def test_fake_agent_llm_guionizado_devuelve_sus_pasos_en_orden():
    llm: AgentLLM = FakeAgentLLM(steps={"Créditos": [FinalText("hola")]})

    assert isinstance(llm, FakeAgentLLM)
    assert llm.steps["Créditos"] == [FinalText("hola")]


@pytest.mark.anyio
async def test_step_convierte_tool_calls_del_modelo():
    chat = ToolChat(AIMessage(content="", tool_calls=[{"id": "c1", "name": "buscar_faq", "args": {"consulta": "plazo"}}]))

    step = await GeminiAgentLLM(cast(BaseChatModel, chat)).step([], TOOLS)

    assert step == ToolCalls([ToolCall("c1", "buscar_faq", {"consulta": "plazo"})])
    assert chat.bound_tools[0]["name"] == "buscar_faq"


@pytest.mark.anyio
async def test_step_devuelve_el_texto_final_como_str():
    step = await GeminiAgentLLM(cast(BaseChatModel, ToolChat(AIMessage(content="Hasta 48 meses")))).step([], TOOLS)

    assert isinstance(step, FinalText)
    assert step == FinalText("Hasta 48 meses") and type(step.text) is str


@pytest.mark.anyio
async def test_step_error_del_proveedor_es_llm_no_disponible():
    with pytest.raises(LlmUnavailableError):
        await GeminiAgentLLM(cast(BaseChatModel, ToolChat(error=TimeoutError("timeout")))).step([], TOOLS)


def test_area_messages_contienen_el_prompt_del_area_y_las_reglas_sin_faq():
    area = AreaInfo(1, "Créditos", "Créditos automotrices", AreaScope.external, "Eres el área de Créditos")

    messages = build_area_messages(area, "Reglas comunes desde la BD", "¿Plazo?", [])
    system = str(messages[0].content)

    assert system.startswith("Área: Créditos")
    assert "Eres el área de Créditos" in system and "Reglas comunes desde la BD" in system
    assert "Pregunta:" not in system
    assert str(messages[-1].content) == "¿Plazo?"
