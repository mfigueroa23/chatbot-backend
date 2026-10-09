import logging
import pytest
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel
from src.agents.llm import AreaInfo, AreaResult, Catalog, FaqHit, Subtask
from src.agents.sub_agent import TOOL_FAILED, run_sub_agent
from src.agents.tools import AreaTool
from src.models.business_area import AreaScope
from src.utils.exceptions.llm import LlmUnavailableError
from tests.fakes import FakeSubAgentModel, answer, tool_call

SAC = AreaInfo(1, "Servicio al Cliente", "Pagos", "Eres SAC.", ("Pagos",))
CATALOG = Catalog(AreaScope.external, "Coordinador externo.", "Reglas.", (SAC,))
FAQS = [FaqHit(7, "Pagos", "¿Cómo pago?", "En la web.")]
QUERY = "cómo pago la cuota"


class Rut(BaseModel):
    rut: str


async def lookup(args: BaseModel) -> str:
    return "Cuota al día"


async def broken(args: BaseModel) -> str:
    raise ConnectionError("detalle interno")


LOOKUP = AreaTool("estado_cuota", "Estado de la cuota", Rut, lookup)
BROKEN = AreaTool("estado_cuota", "Estado de la cuota", Rut, broken)


async def run(model, tools=(), max_steps=3, timeout=5.0):
    return await run_sub_agent(model, CATALOG, SAC, FAQS, Subtask(1, QUERY), list(tools), max_steps, timeout)


@pytest.mark.anyio
async def test_recibe_solo_su_subtarea_su_prompt_y_sus_faq_sin_historial():
    model = FakeSubAgentModel({QUERY: [answer(True, "Pague en la web.")]})

    result = await run(model)

    messages = model.calls[0].messages
    assert result == AreaResult(1, "Servicio al Cliente", QUERY, True, "Pague en la web.")
    assert len(messages) == 2 and isinstance(messages[0], SystemMessage) and messages[1] == HumanMessage(QUERY)
    assert "Eres SAC." in str(messages[0].content) and "En la web." in str(messages[0].content)


@pytest.mark.anyio
async def test_sin_herramientas_hace_una_sola_llamada_que_solo_puede_responder():
    model = FakeSubAgentModel()

    await run(model)

    assert len(model.calls) == 1 and model.calls[0].answer_only and model.calls[0].tools == []


@pytest.mark.anyio
@pytest.mark.parametrize("reply", [answer(False), answer(True, "   ")])
async def test_sin_informacion_devuelve_found_false(reply):
    result = await run(FakeSubAgentModel({QUERY: [reply]}))

    assert result.found is False and result.content == ""


@pytest.mark.anyio
async def test_usa_una_herramienta_y_luego_responde():
    model = FakeSubAgentModel({QUERY: [tool_call("estado_cuota", {"rut": "1-9"}), answer(True, "Su cuota está al día.")]})

    result = await run(model, [LOOKUP])

    second = model.calls[1].messages
    assert result.found and result.content == "Su cuota está al día."
    assert model.calls[0].tools == ["estado_cuota"] and not model.calls[0].answer_only
    assert isinstance(second[-1], ToolMessage) and second[-1].content == "Cuota al día"


@pytest.mark.anyio
async def test_una_herramienta_que_falla_devuelve_un_aviso_generico(caplog):
    model = FakeSubAgentModel({QUERY: [tool_call("estado_cuota", {"rut": "1-9"}), answer(False)]})

    with caplog.at_level(logging.WARNING, logger="src"):
        await run(model, [BROKEN])

    assert model.calls[1].messages[-1].content == TOOL_FAILED
    assert "estado_cuota" in caplog.text and "detalle interno" not in caplog.text


@pytest.mark.anyio
async def test_al_llegar_al_tope_de_pasos_fuerza_responder():
    model = FakeSubAgentModel({QUERY: [tool_call("estado_cuota", {"rut": "1-9"})] * 2 + [answer(True, "Al día.")]})

    result = await run(model, [LOOKUP], max_steps=2)

    assert [call.answer_only for call in model.calls] == [False, True] and model.calls[1].tools == []
    assert result.found is False  # el guion no respondió en el paso forzado: no hay información


@pytest.mark.anyio
async def test_timeout_del_sub_agente_devuelve_found_false(caplog):
    with caplog.at_level(logging.WARNING, logger="src"):
        result = await run(FakeSubAgentModel(delay=1.0), timeout=0.05)

    assert result == AreaResult(1, "Servicio al Cliente", QUERY, False)
    assert "Servicio al Cliente" in caplog.text and QUERY not in caplog.text


@pytest.mark.anyio
async def test_error_del_modelo_devuelve_found_false_como_un_timeout(caplog):
    model = FakeSubAgentModel({QUERY: [LlmUnavailableError("cuota excedida")]})

    with caplog.at_level(logging.WARNING, logger="src"):
        result = await run(model)

    assert result.found is False and "LlmUnavailableError" in caplog.text and "cuota excedida" not in caplog.text
