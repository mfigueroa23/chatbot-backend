import pytest
from src.cli.jailbreak_check import ATTACKS, GENERIC_REFUSAL, TOOL_NAMES, find_leaks, main, run_battery

# Texto ficticio: los prompts reales solo viven en la BD.
PROMPT = "Texto ficticio de un prompt de sistema que el asistente no debe revelar nunca al usuario."


def test_leak_detecta_un_fragmento_de_30_o_mas_caracteres_de_un_prompt():
    reply = "Claro, aquí va: texto ficticio de un prompt de sistema que el asistente no debe revelar."

    assert find_leaks(reply, [PROMPT], TOOL_NAMES, []) == ["fragmento del prompt"]


def test_leak_detecta_el_nombre_de_una_tool():
    assert find_leaks("Puedo usar buscar_procedimiento y otras", [PROMPT], TOOL_NAMES, []) == ["tool buscar_procedimiento"]


def test_leak_detecta_un_area_interna():
    assert find_leaks("Eso lo ve el área de Remuneraciones", [PROMPT], TOOL_NAMES, ["Remuneraciones"]) == ["área interna Remuneraciones"]


def test_leak_no_marca_la_negativa_generica():
    assert find_leaks(GENERIC_REFUSAL, [PROMPT], TOOL_NAMES, ["Remuneraciones"]) == []


def test_battery_tiene_al_menos_20_ataques_distintos():
    assert len(set(ATTACKS)) >= 20


@pytest.mark.anyio
async def test_runner_marca_solo_los_ataques_con_fuga():
    async def ask(attack: str) -> str:
        return "Uso buscar_faq" if attack == ATTACKS[0] else GENERIC_REFUSAL

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
