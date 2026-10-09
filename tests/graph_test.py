import asyncio
from collections.abc import Sequence
import pytest
from pydantic import BaseModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from src.agents.graph import AgentContext, Limits, run_graph
from src.agents.llm import AreaInfo, Catalog, FaqHit, RoutingDecision, SubAgentModel, Subtask
from src.agents.tools.registry import AreaTool, ToolContext, code_tool
from src.models.business_area import AreaScope
from src.utils.exceptions.llm import LlmUnavailableError
from tests.fakes import FakeCoordinatorModel, FakeKnowledge, FakeSubAgentModel, answer

SAC = AreaInfo(1, "Servicio al Cliente", "Pagos", "Eres SAC.", ("Pagos",))
SALES = AreaInfo(2, "Ventas", "Créditos", "Eres Ventas.", ("Créditos",))
PEOPLE = AreaInfo(10, "Personas", "Remuneraciones", "Eres Personas.", ("Bonos",))
EXTERNAL = Catalog(AreaScope.external, "Coordinador externo.", "Reglas.", (SAC, SALES))
INTERNAL = Catalog(AreaScope.internal, "Coordinador interno.", "Reglas.", (PEOPLE,))
LIMITS = Limits(max_areas=3, faqs_per_search=5, sub_agent_max_steps=3, sub_agent_timeout=1.0)
TWO_AREAS = RoutingDecision("areas", (Subtask(1, "cómo pago la cuota"), Subtask(2, "qué crédito me conviene")))


def context(coordinator, sub_agent=None, catalog=EXTERNAL, knowledge=None) -> AgentContext:
    return AgentContext(catalog, coordinator, sub_agent or FakeSubAgentModel(), knowledge or FakeKnowledge(), LIMITS)


def results_block(coordinator: FakeCoordinatorModel) -> str:
    system = str(coordinator.synthesize_calls[0][0].content)
    return system[system.index("<informacion"):system.index("</informacion>")]


@pytest.mark.anyio
async def test_respuesta_directa_hace_una_sola_llamada():
    coordinator, sub_agent = FakeCoordinatorModel(RoutingDecision("direct", reply="¡Hola!")), FakeSubAgentModel()

    reply = await run_graph(context(coordinator, sub_agent), [], "hola")

    assert reply == "¡Hola!"
    assert (len(coordinator.route_calls), len(sub_agent.calls), len(coordinator.synthesize_calls)) == (1, 0, 0)


@pytest.mark.anyio
async def test_dos_areas_hacen_dos_mas_n_llamadas_y_una_sola_respuesta():
    coordinator, sub_agent = FakeCoordinatorModel(TWO_AREAS, reply="Cuota y crédito."), FakeSubAgentModel()
    knowledge = FakeKnowledge({1: [FaqHit(7, "Pagos", "¿Cómo pago?", "En la web.")]})

    reply = await run_graph(context(coordinator, sub_agent, knowledge=knowledge), [], "¿Cuota y crédito?")

    assert reply == "Cuota y crédito."
    assert len(coordinator.route_calls) + len(sub_agent.calls) + len(coordinator.synthesize_calls) == 2 + 2
    assert knowledge.searches == [(list(TWO_AREAS.subtasks), 5)]
    assert results_block(coordinator).index("Servicio al Cliente") < results_block(coordinator).index("Ventas")


class WaitsForTheOther(SubAgentModel):
    """Cada sub-agente espera a que el otro haya empezado: solo terminan si corren en paralelo."""

    def __init__(self, queries: list[str]):
        self.started = {query: asyncio.Event() for query in queries}

    async def step(self, messages: list[BaseMessage], tools: Sequence[AreaTool], answer_only: bool) -> AIMessage:
        query = str(messages[-1].content)
        self.started[query].set()
        other = next(event for name, event in self.started.items() if name != query)
        await other.wait()
        return answer(True, f"Listo: {query}")


@pytest.mark.anyio
async def test_las_subtareas_se_ejecutan_en_paralelo():
    coordinator = FakeCoordinatorModel(TWO_AREAS)

    await run_graph(context(coordinator, WaitsForTheOther([s.query for s in TWO_AREAS.subtasks])), [], "x")

    # En serie, el primero esperaría al segundo hasta el timeout del sub-agente y quedaría sin información.
    assert results_block(coordinator).count("Encontrado: sí") == 2


@pytest.mark.anyio
async def test_un_sub_agente_caido_no_impide_la_respuesta():
    coordinator = FakeCoordinatorModel(TWO_AREAS, reply="Solo sobre el crédito.")
    sub_agent = FakeSubAgentModel({"cómo pago la cuota": [LlmUnavailableError("caído")]})

    reply = await run_graph(context(coordinator, sub_agent), [], "¿Cuota y crédito?")

    assert reply == "Solo sobre el crédito."
    assert results_block(coordinator).count("Encontrado: no") == 1


@pytest.mark.anyio
async def test_sin_subtareas_validas_redacta_que_no_tiene_informacion():
    coordinator = FakeCoordinatorModel(RoutingDecision("areas", (Subtask(404, "tasa de hoy"),)), reply="No tengo eso.")
    sub_agent = FakeSubAgentModel()

    reply = await run_graph(context(coordinator, sub_agent), [], "¿Tasa de hoy?")

    assert reply == "No tengo eso." and sub_agent.calls == [] and len(coordinator.synthesize_calls) == 1


@pytest.mark.anyio
async def test_un_area_nueva_del_catalogo_funciona_sin_codigo():
    insurance = AreaInfo(3, "Seguros", "Siniestros", "Eres Seguros.", ("Siniestros",))
    catalog = Catalog(AreaScope.external, "Coordinador externo.", "Reglas.", (SAC, SALES, insurance))
    sub_agent = FakeSubAgentModel()

    await run_graph(context(FakeCoordinatorModel(RoutingDecision("areas", (Subtask(3, "siniestro"),))), sub_agent,
                            catalog), [], "Choqué")

    assert "Eres Seguros." in str(sub_agent.calls[0].messages[0].content)


@pytest.mark.anyio
@pytest.mark.parametrize("catalog, prompt, other", [(EXTERNAL, "Coordinador externo.", "Personas"),
                                                    (INTERNAL, "Coordinador interno.", "Ventas")])
async def test_cada_canal_usa_su_coordinador_y_solo_sus_areas(catalog, prompt, other):
    coordinator = FakeCoordinatorModel()

    await run_graph(context(coordinator, catalog=catalog), [], "hola")

    system = str(coordinator.route_calls[0][0].content)
    assert prompt in system and other not in system


@pytest.mark.anyio
async def test_el_historial_llega_al_coordinador_y_no_a_los_sub_agentes():
    history = [HumanMessage("¿Cómo prepago?"), AIMessage("En la web.")]
    coordinator, sub_agent = FakeCoordinatorModel(TWO_AREAS), FakeSubAgentModel()

    await run_graph(context(coordinator, sub_agent), history, "¿y el seguro?")

    assert coordinator.route_calls[0][1:3] == history and coordinator.synthesize_calls[0][1:3] == history
    assert all(len(call.messages) == 2 for call in sub_agent.calls)


class Clave(BaseModel):
    clave: str


async def read_ticket(args: Clave, context: ToolContext) -> str:
    return f"{args.clave} en curso"


TICKET = code_tool("leer_ticket", "Lee un ticket de Jira.", Clave, read_ticket)
PROJECTS = AreaInfo(3, "Proyectos", "Jira y EDR", "Eres Proyectos.", ("EDR",), ("leer_ticket",),
                    members=frozenset({"jp@autofin.cl"}))
PROJECTS_ROUTE = RoutingDecision("areas", (Subtask(3, "estado de DAIA-52"),))


def projects_context(sub_agent, requester, area=PROJECTS) -> AgentContext:
    catalog = Catalog(AreaScope.internal, "Coordinador interno.", "Reglas.", (area,))
    return AgentContext(catalog, FakeCoordinatorModel(PROJECTS_ROUTE), sub_agent, FakeKnowledge(), LIMITS,
                        {"leer_ticket": TICKET}, requester=requester)


@pytest.mark.anyio
async def test_access_un_habilitado_recibe_las_herramientas_del_area():
    sub_agent = FakeSubAgentModel()

    await run_graph(projects_context(sub_agent, "jp@autofin.cl"), [], "¿en qué está DAIA-52?")

    assert sub_agent.calls[0].tools == ["leer_ticket"]
    assert "no está habilitada" not in str(sub_agent.calls[0].messages[0].content)


@pytest.mark.anyio
@pytest.mark.parametrize("requester", ["otra@autofin.cl", None])
async def test_access_un_no_habilitado_no_las_recibe_y_ve_la_nota(requester):
    sub_agent = FakeSubAgentModel()

    await run_graph(projects_context(sub_agent, requester), [], "¿en qué está DAIA-52?")

    system = str(sub_agent.calls[0].messages[0].content)
    assert sub_agent.calls[0].tools == [] and "no está habilitada" in system and "Lee un ticket de Jira" in system


@pytest.mark.anyio
async def test_access_un_cambio_de_miembros_se_aplica_en_el_siguiente_mensaje():
    sub_agent = FakeSubAgentModel()
    enabled_later = AreaInfo(3, "Proyectos", "Jira y EDR", "Eres Proyectos.", ("EDR",), ("leer_ticket",),
                             members=frozenset({"jp@autofin.cl", "otra@autofin.cl"}))

    await run_graph(projects_context(sub_agent, "otra@autofin.cl"), [], "x")
    await run_graph(projects_context(sub_agent, "otra@autofin.cl", enabled_later), [], "x")

    assert [call.tools for call in sub_agent.calls] == [[], ["leer_ticket"]]
