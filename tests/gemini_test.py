import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel
from src.agents.gemini import GeminiCoordinator, GeminiSubAgent, RouteOutput, SubtaskOutput, gemini_models, tool_specs
from src.agents.llm import ANSWER_TOOL, RoutingDecision, Subtask
from src.agents.tools import AreaTool
from src.services.property import Properties
from src.utils.exceptions.llm import LlmUnavailableError
from src.utils.exceptions.property import PropertyNotFoundError
from tests.fakes import answer

MESSAGES: list[BaseMessage] = [HumanMessage("hola")]


def fails(*_):
    raise ConnectionError("detalle del proveedor con parte del prompt")


def coordinator(router=None, writer=None) -> GeminiCoordinator:
    return GeminiCoordinator(RunnableLambda(router or fails), RunnableLambda(writer or fails))


@pytest.mark.anyio
async def test_route_convierte_la_salida_estructurada():
    output = RouteOutput(tipo="areas", subtareas=[SubtaskOutput(area_id=1, consulta="cómo pago")])

    decision = await coordinator(router=lambda _: output).route(MESSAGES)

    assert decision == RoutingDecision("areas", (Subtask(1, "cómo pago"),))


@pytest.mark.anyio
async def test_route_directa_trae_la_respuesta():
    decision = await coordinator(router=lambda _: RouteOutput(tipo="directa", respuesta="¡Hola!")).route(MESSAGES)

    assert decision == RoutingDecision("direct", reply="¡Hola!")


@pytest.mark.anyio
async def test_route_sin_salida_valida_es_servicio_no_disponible():
    with pytest.raises(LlmUnavailableError):
        await coordinator(router=lambda _: None).route(MESSAGES)


@pytest.mark.anyio
async def test_synthesize_devuelve_el_texto():
    assert await coordinator(writer=lambda _: AIMessage("Respuesta.")).synthesize(MESSAGES) == "Respuesta."


@pytest.mark.anyio
@pytest.mark.parametrize("call", ["route", "synthesize"])
async def test_un_error_del_proveedor_es_llm_unavailable_sin_detalle(call):
    with pytest.raises(LlmUnavailableError) as error:
        await getattr(coordinator(), call)(MESSAGES)

    assert str(error.value) == "ConnectionError"


class Rut(BaseModel):
    rut: str


async def lookup(args: BaseModel) -> str:
    return "ok"


TOOL = AreaTool("estado_cuota", "Estado de la cuota", Rut, lookup)


def test_tool_specs_siempre_incluye_responder():
    names = [spec["name"] for spec in tool_specs([TOOL])]

    assert names == [ANSWER_TOOL, "estado_cuota"] and [s["name"] for s in tool_specs([])] == [ANSWER_TOOL]
    assert set(tool_specs([])[0]["parameters"]["properties"]) == {"encontrado", "contenido"}


@pytest.mark.anyio
@pytest.mark.parametrize("answer_only, expected", [(False, [ANSWER_TOOL, "estado_cuota"]), (True, [ANSWER_TOOL])])
async def test_sub_agente_enlaza_solo_responder_cuando_debe_responder(answer_only, expected):
    bound: list[list[str]] = []

    def bind(specs):
        bound.append([spec["name"] for spec in specs])
        return RunnableLambda(lambda _: answer(True, "Listo."))

    reply = await GeminiSubAgent(bind).step(MESSAGES, [TOOL], answer_only)

    assert bound == [expected] and reply.tool_calls[0]["name"] == ANSWER_TOOL


@pytest.mark.anyio
async def test_sub_agente_con_error_del_proveedor_es_llm_unavailable():
    with pytest.raises(LlmUnavailableError):
        await GeminiSubAgent(lambda _: RunnableLambda(fails)).step(MESSAGES, [], True)


@pytest.mark.parametrize("missing", ["gemini_api_key", "coordinator_model", "sub_agent_model", "embedding_model"])
def test_falta_configuracion_obligatoria(missing):
    values = {"gemini_api_key": "clave", "coordinator_model": "m", "sub_agent_model": "m", "embedding_model": "e"}
    del values[missing]

    with pytest.raises(PropertyNotFoundError) as error:
        gemini_models(Properties(values))

    assert error.value.key == missing
