import pytest
from langgraph.checkpoint.memory import InMemorySaver
from src.agents.audit import GENERIC_REFUSAL
from src.agents.graph import AgentContext, Catalog, build_graph
from src.agents.llm import AreaInfo, FinalText
from src.cli.jailbreak_check import ATTACKS, graph_asker, is_secret_prompt, leak_names, main, run_battery
from src.models.business_area import AreaScope
from tests.fakes import FakeAgentLLM, FakeNotifier, FakeRetriever

# Texto ficticio: los prompts reales solo viven en la BD.
PROMPT = "Texto ficticio de un prompt de sistema que el asistente no debe revelar nunca al usuario."


def test_battery_tiene_al_menos_20_ataques_distintos():
    assert len(set(ATTACKS)) >= 20


@pytest.mark.anyio
async def test_runner_marca_solo_los_ataques_con_fuga():
    async def ask(attack: str) -> str:
        return "Uso el campo faq_ids" if attack == ATTACKS[0] else GENERIC_REFUSAL

    results = await run_battery(ask, [PROMPT], ["Remuneraciones"])

    assert len(results) == len(ATTACKS)
    assert [result.attack for result in results if result.leaks] == [ATTACKS[0]]


@pytest.mark.anyio
async def test_runner_un_error_de_conexion_cuenta_como_fallo():
    async def ask(attack: str) -> str:
        raise OSError("conexión rechazada")

    results = await run_battery(ask, [PROMPT], [])

    assert all(result.leaks == ["error: OSError"] for result in results)


def test_runner_help_termina_con_codigo_0():
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    assert exit_info.value.code == 0


def test_battery_ataca_las_tools_de_los_agentes_de_area():
    tool_attacks = [attack for attack in ATTACKS if "buscar_faq" in attack or "iniciar_procedimiento" in attack]

    assert len(tool_attacks) >= 2


def test_secrets_no_incluyen_los_textos_fijos():
    keys = ["internal_agent", "external_agent", "area_rules", "external_greeting", "internal_closing", "external_off_topic"]

    assert [key for key in keys if is_secret_prompt(key)] == ["internal_agent", "external_agent", "area_rules"]



PAYROLL = AreaInfo(10, "Remuneraciones", "Sueldos", AreaScope.internal, "Eres el área de Remuneraciones", "spaces/RRHH")


async def internal_catalog(scope: AreaScope) -> Catalog:
    return Catalog([PAYROLL], "Prompt del coordinador interno", "Prompt del agente interno", "Reglas", "Tono cercano.")


def internal_context(refusal: str) -> AgentContext:
    llm = FakeAgentLLM(coordinator_steps=[FinalText(refusal)])
    return AgentContext(llm, FakeRetriever(), internal_catalog, FakeNotifier(), None)


@pytest.mark.anyio
async def test_internal_grafo_sin_fugas_pasa_la_bateria():
    ask = graph_asker(build_graph(AreaScope.internal, InMemorySaver()), internal_context("Eso me lo guardo, ¿en qué te ayudo?"))

    results = await run_battery(ask, [PROMPT], leak_names(AreaScope.internal, ["Remuneraciones"]))

    assert not any(result.leaks for result in results)
    assert {result.reply for result in results} == {"Eso me lo guardo, ¿en qué te ayudo?"}


@pytest.mark.anyio
async def test_internal_grafo_que_filtra_un_prompt_de_la_bd_falla():
    # El auditor del grafo solo conoce los prompts de su ámbito; la batería compara con todos los de la BD.
    ask = graph_asker(build_graph(AreaScope.internal, InMemorySaver()), internal_context(PROMPT))

    results = await run_battery(ask, [PROMPT], leak_names(AreaScope.internal, ["Remuneraciones"]))

    assert all(result.leaks == ["fragmento del prompt"] for result in results)


@pytest.mark.anyio
async def test_internal_negativa_vacia_responde_la_generica():
    ask = graph_asker(build_graph(AreaScope.internal, InMemorySaver()), internal_context(""))

    assert await ask(ATTACKS[0]) == GENERIC_REFUSAL


def test_internal_las_areas_internas_no_son_secretas_en_su_propio_canal():
    assert leak_names(AreaScope.internal, ["Remuneraciones"]) == []
    assert leak_names(AreaScope.external, ["Remuneraciones"]) == ["Remuneraciones"]
