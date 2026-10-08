import pytest
from src.agents.audit import GENERIC_REFUSAL
from src.cli.jailbreak_check import ATTACKS, is_secret_prompt, main, run_battery

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
