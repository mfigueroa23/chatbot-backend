import logging
from typing import cast
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from src.agents.llm import (
    AgentLLM, AgentReply, AreaInfo, AreaSection, FaqHit, GeminiAgentLLM, ReplyData, ReplyOutput, build_gemini_llm,
    build_reply_messages)
from src.agents.retriever import ProcedureHit
from src.models.business_area import AreaScope
from src.models.procedure_field import FieldKind
from src.services.procedures import FieldSpec, web_contact_fields
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


@pytest.mark.anyio
async def test_respond_traduce_la_salida_estructurada():
    output = ReplyOutput(kind="procedure", text="Te explico", faq_ids=[], procedure_id=7,
                         data=[ReplyData(campo="rut", valor="12.345.678-5")])

    reply = await GeminiAgentLLM(cast(BaseChatModel, StructuredChat(output))).respond([HumanMessage("Quiero mi contrato")])

    assert reply == AgentReply("procedure", "Te explico", [], 7, {"rut": "12.345.678-5"})


@pytest.mark.anyio
async def test_respond_error_del_proveedor_es_llm_no_disponible():
    with pytest.raises(LlmUnavailableError):
        await GeminiAgentLLM(cast(BaseChatModel, StructuredChat(error=TimeoutError("timeout")))).respond([])


CREDITS = AreaInfo(1, "Créditos", "Créditos automotrices", AreaScope.external, "Eres el área de Créditos")
SECTION = AreaSection(CREDITS, [FaqHit("¿Plazo?", "Hasta 48 meses", 0.9, id=11, area_id=1)],
                      [ProcedureHit(7, "Copia del contrato", "Se envía al correo", [FieldSpec("rut", "RUT del titular", FieldKind.rut)], 0.9, 1)])


def test_reply_messages_incluyen_prompts_ids_y_datos_exigidos():
    messages = build_reply_messages("Prompt del agente", "Reglas", [SECTION], None, [], "¿Plazo?", 20, web_contact_fields())
    system = str(messages[0].content)

    assert system.startswith("Prompt del agente") and "Reglas" in system
    assert "Eres el área de Créditos" in system and "[F11]" in system and "Hasta 48 meses" in system
    assert "[P7] Copia del contrato" in system and "RUT del titular (campo: rut)" in system
    assert "Correo o teléfono (campo: contacto)" in system
    assert str(messages[-1].content) == "¿Plazo?"


def test_reply_messages_sin_contenido_lo_indican_y_no_inventan_secciones():
    system = str(build_reply_messages("Prompt", "Reglas", [], None, [], "Hola", 20, [])[0].content)

    assert "No se encontró información" in system and "[F" not in system and "[P" not in system


def test_reply_messages_incluyen_el_procedimiento_en_curso():
    pending = ProcedureHit(7, "Copia del contrato", "Se envía", [FieldSpec("rut", "RUT del titular", FieldKind.rut)], 1.0, 1)

    system = str(build_reply_messages("Prompt", "Reglas", [], pending, [], "Mi RUT", 20, [])[0].content)

    assert "Procedimiento en curso" in system and "[P7] Copia del contrato" in system


def test_reply_messages_cortan_el_historial_en_un_mensaje_del_usuario():
    history = [HumanMessage("q1"), AIMessage("a1"), HumanMessage("q2"), AIMessage("a2"), HumanMessage("q3"), AIMessage("a3")]

    messages = build_reply_messages("Prompt", "Reglas", [], None, history, "q4", 3, [])

    assert [str(m.content) for m in messages[1:]] == ["q3", "a3", "q4"]
