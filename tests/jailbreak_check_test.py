import pytest
from src.agents.audit import GENERIC_REFUSAL
from src.cli.jailbreak_check import ATTACKS, main, run_battery

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
