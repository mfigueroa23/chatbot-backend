import pytest
from langchain_core.messages import BaseMessage
from langgraph.checkpoint.memory import InMemorySaver
from src.agents.behavior import ClarifyOption
from src.agents.graph import AgentContext, Catalog, build_graph
from src.agents.llm import AreaInfo, CoordinatorReply, FaqHit, FinalText
from src.agents.retriever import ProcedureHit
from src.cli.behavior_check import (
    CLASSIFICATION, choice_cases, graph_chooser, graph_classifier, main, run_choices, run_classification)
from src.models.business_area import AreaScope
from tests.fakes import FakeAgentLLM, FakeNotifier, FakeRetriever

CREDITS = AreaInfo(1, "Créditos", "Créditos automotrices", AreaScope.external, "Eres el área de Créditos", "spaces/CREDITOS")
TERM = FaqHit("¿Plazo máximo?", "Hasta 48 meses", 0.9, id=11, area_id=1)
RATE = FaqHit("¿Tasa de interés?", "Desde 1,2 %", 0.9, id=12, area_id=1)
CONTRACT = ProcedureHit(7, "Copia del contrato", "El área envía la copia", [], 0.9, area_id=1)
OPTIONS = [ClarifyOption(1, "faq", 11, 1, "¿Plazo máximo del crédito?"), ClarifyOption(2, "faq", 12, 1, "¿Tasa de interés del crédito?"),
           ClarifyOption(3, "procedure", 7, 1, "Copia del contrato")]
EXPECTED_KIND = {"greeting": CoordinatorReply("greeting"), "closing": CoordinatorReply("closing"),
                 "off_topic": CoordinatorReply("off_topic"), "other": CoordinatorReply("no_answer")}


async def load_catalog(scope: AreaScope) -> Catalog:
    fixed: dict[str, str | None] = {"greeting": "¡Hola!", "closing": "¡Con gusto!", "off_topic": "No puedo ayudarte con eso."}
    return Catalog([CREDITS], "Prompt", "Reglas", fixed, ["Créditos"])


class ScriptedCoordinator(FakeAgentLLM):
    """Decide por el texto del mensaje, como lo haría el modelo real."""

    def __init__(self, decisions: dict[str, CoordinatorReply], **kwargs):
        super().__init__(**kwargs)
        self.decisions = decisions

    async def coordinate(self, messages: list[BaseMessage]) -> CoordinatorReply:
        self.coordinator_calls += 1
        return self.decisions[str(messages[-1].content)]


def context(llm: FakeAgentLLM) -> AgentContext:
    return AgentContext(llm, FakeRetriever(stored_faqs=[TERM, RATE], stored=[CONTRACT]), load_catalog, FakeNotifier(), None)


@pytest.mark.anyio
async def test_clasificacion_acierta_con_un_modelo_que_clasifica_bien():
    cases = [case for case in CLASSIFICATION if AreaScope.external in case.scopes]
    llm = ScriptedCoordinator({case.message: EXPECTED_KIND[str(case.expected)] for case in cases})
    graph = build_graph(AreaScope.external, InMemorySaver())

    results = await run_classification(graph_classifier(graph, context(llm)), AreaScope.external)

    assert len(results) == len(cases) and all(result.ok for result in results)


@pytest.mark.anyio
async def test_clasificacion_marca_los_fallos():
    cases = [case for case in CLASSIFICATION if AreaScope.external in case.scopes]
    llm = ScriptedCoordinator({case.message: CoordinatorReply("greeting") for case in cases})
    graph = build_graph(AreaScope.external, InMemorySaver())

    results = await run_classification(graph_classifier(graph, context(llm)), AreaScope.external)

    assert {result.case.message for result in results if not result.ok} == {
        case.message for case in cases if case.expected != "greeting"}


def test_clasificacion_respeta_los_casos_solo_web():
    internal = {case.message for case in CLASSIFICATION if AreaScope.internal in case.scopes}

    assert "¿cuántos días de vacaciones me quedan?" not in internal and "hola" in internal


@pytest.mark.anyio
async def test_eleccion_acierta_y_detecta_la_opcion_atendida():
    cases = choice_cases(OPTIONS, "Quiero saber cuánto interés me cobran")
    decisions = {case.message: CoordinatorReply("choice", chosen_options=sorted(case.expected))
                 if isinstance(case.expected, frozenset) else
                 CoordinatorReply("closing" if case.expected == "closing" else "choice", chosen_options=[4])
                 for case in cases}
    llm = ScriptedCoordinator(decisions, steps={"Créditos": [FinalText("Respuesta del área")]})
    graph = build_graph(AreaScope.external, InMemorySaver())

    results = await run_choices(graph_chooser(graph, context(llm), OPTIONS), cases)

    assert [result.case.message for result in results if not result.ok] == []
    assert len(results) == 10


@pytest.mark.anyio
async def test_eleccion_marca_una_opcion_equivocada():
    cases = choice_cases(OPTIONS, "Quiero saber cuánto interés me cobran")
    llm = ScriptedCoordinator({case.message: CoordinatorReply("choice", chosen_options=[1]) for case in cases},
                              steps={"Créditos": [FinalText("Respuesta del área")]})
    graph = build_graph(AreaScope.external, InMemorySaver())

    results = await run_choices(graph_chooser(graph, context(llm), OPTIONS), cases)

    assert not any(result.ok for result in results if result.case.expected == frozenset({2}))


def test_eleccion_incluye_el_texto_parcial_y_la_parafrasis():
    messages = [case.message for case in choice_cases(OPTIONS, "Quiero saber cuánto interés me cobran")]

    assert "¿Tasa de interés" in messages and "Quiero saber cuánto interés me cobran" in messages


def test_runner_help_termina_con_codigo_0():
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    assert exit_info.value.code == 0
