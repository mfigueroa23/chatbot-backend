import logging
from datetime import UTC, datetime, time
from typing import cast
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents import strategies
from src.agents.llm import AreaInfo
from src.agents.strategies import ExternalStrategy, InternalStrategy, NoAnswerContext
from src.models.business_area import AreaScope
from src.models.official_channel import OfficialChannel
from tests.fakes import FakeClock, FakeNotifier

SESSION = cast(AsyncSession, object())
PAYROLL = AreaInfo(10, "Remuneraciones", "Sueldos", AreaScope.internal, "Eres Remuneraciones", "spaces/RRHH")
CONTEXT = NoAnswerContext("¿Cuándo pagan el bono?", [PAYROLL], "Ana Pérez", "ana@autofin.cl")


@pytest.fixture(autouse=True)
def business_data(monkeypatch: pytest.MonkeyPatch):
    async def load_schedule(session):
        return {weekday: (time(9, 0), time(18, 0)) for weekday in range(5)}, set()

    async def get_official_channels(session):
        return [OfficialChannel(label="Teléfono", value="600 123 4567")]

    async def get_fallback_space(session, scope):
        return "spaces/GENERAL"

    monkeypatch.setattr(strategies, "load_schedule", load_schedule)
    monkeypatch.setattr(strategies, "get_official_channels", get_official_channels)
    monkeypatch.setattr(strategies, "get_fallback_space", get_fallback_space)


@pytest.mark.anyio
async def test_external_dentro_de_horario_ofrece_un_ejecutivo():
    # Miércoles a las 12:00 en Santiago.
    strategy = ExternalStrategy(SESSION, FakeClock(datetime(2026, 10, 7, 15, tzinfo=UTC)))

    reply = await strategy.on_no_answer(NoAnswerContext("¿Puedo pagar con cheque?", []))

    assert reply.offer_human
    assert reply.channels == []


@pytest.mark.anyio
async def test_external_fuera_de_horario_pide_reformular_y_muestra_canales():
    strategy = ExternalStrategy(SESSION, FakeClock(datetime(2026, 10, 7, 23, tzinfo=UTC)))

    reply = await strategy.on_no_answer(NoAnswerContext("¿Puedo pagar con cheque?", []))

    assert not reply.offer_human
    assert "reformula" in reply.text
    assert reply.channels == [("Teléfono", "600 123 4567")]


@pytest.mark.anyio
async def test_internal_avisa_en_el_space_del_area():
    notifier = FakeNotifier()

    reply = await InternalStrategy(SESSION, notifier).on_no_answer(CONTEXT)

    space, text = notifier.sent[0]
    assert space == "spaces/RRHH"
    assert "¿Cuándo pagan el bono?" in text and "Ana Pérez" in text and "ana@autofin.cl" in text
    assert "Área: Remuneraciones" in text
    assert "te contactará a la brevedad" in reply.text


@pytest.mark.anyio
async def test_internal_sin_area_avisa_en_el_space_general():
    notifier = FakeNotifier()

    await InternalStrategy(SESSION, notifier).on_no_answer(NoAnswerContext("¿Dónde está el casino?", [], "Ana Pérez", "ana@autofin.cl"))

    assert notifier.sent[0][0] == "spaces/GENERAL"


@pytest.mark.anyio
async def test_internal_area_sin_space_cuenta_como_notificacion_fallida(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.ERROR)
    notifier = FakeNotifier()
    no_space = AreaInfo(11, "Beneficios", "Beneficios", AreaScope.internal, "Eres Beneficios", None)

    reply = await InternalStrategy(SESSION, notifier).on_no_answer(NoAnswerContext("¿Bono?", [no_space], "Ana", "ana@autofin.cl"))

    assert notifier.sent == []
    assert "contacta directamente" in reply.text
    assert "No se pudo avisar al área" in caplog.text


@pytest.mark.anyio
async def test_internal_si_falla_el_aviso_lo_registra_y_pide_contactar_al_area(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.ERROR)

    reply = await InternalStrategy(SESSION, FakeNotifier(fail=True)).on_no_answer(CONTEXT)

    assert "No se pudo avisar al área" in caplog.text
    assert "contacta directamente" in reply.text
