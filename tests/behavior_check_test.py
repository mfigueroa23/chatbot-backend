import pytest
from langgraph.checkpoint.memory import InMemorySaver
from src.agents.graph import AgentContext, Catalog, build_graph
from src.agents.llm import AreaInfo, FinalText
from src.cli.behavior_check import graph_greeter, main, required_variety, run_variety
from src.models.business_area import AreaScope
from tests.fakes import FakeAgentLLM, FakeNotifier, FakeRetriever

PAYROLL = AreaInfo(10, "Remuneraciones", "Sueldos", AreaScope.internal, "Eres Remuneraciones", "spaces/RRHH")


async def load_catalog(scope: AreaScope) -> Catalog:
    return Catalog([PAYROLL], "Prompt del coordinador", "Prompt del ámbito", "Reglas")


def context(llm: FakeAgentLLM) -> AgentContext:
    return AgentContext(llm, FakeRetriever(), load_catalog, FakeNotifier(), None)


def test_runner_help_termina_con_codigo_0():
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    assert exit_info.value.code == 0


@pytest.mark.parametrize(("count", "required"), [(5, 3), (3, 2), (10, 6), (1, 1)])
def test_variety_exige_tres_de_cada_cinco(count, required):
    assert required_variety(count) == required


@pytest.mark.anyio
@pytest.mark.parametrize("scope", [AreaScope.internal, AreaScope.external])
@pytest.mark.parametrize(("texts", "ok"), [(["¡Hola!", "¡Buenas!", "¡Qué tal!", "¡Hola!", "¡Buenas!"], True),
                                           (["¡Hola!", "¡Hola!", "¡Buenas!", "¡Hola!", "¡Buenas!"], False)])
async def test_variety_cuenta_los_saludos_distintos_en_hilos_nuevos(texts, ok, scope):
    llm = FakeAgentLLM(coordinator_steps=[FinalText(text) for text in texts])
    graph = build_graph(scope, InMemorySaver())

    replies, passed = await run_variety(graph_greeter(graph, context(llm)), len(texts))

    assert replies == texts and passed is ok
