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
from tests.fakes import FakeClock, FakeMailer

SESSION = cast(AsyncSession, object())
PAYROLL = AreaInfo(10, "Remuneraciones", "Sueldos", AreaScope.internal, "Eres Remuneraciones", "rrhh@autofin.cl")
CONTEXT = NoAnswerContext("¿Cuándo pagan el bono?", [PAYROLL], "Ana Pérez", "ana@autofin.cl")


@pytest.fixture(autouse=True)
def business_data(monkeypatch: pytest.MonkeyPatch):
    async def load_schedule(session):
        return {weekday: (time(9, 0), time(18, 0)) for weekday in range(5)}, set()

    async def get_official_channels(session):
        return [OfficialChannel(label="Teléfono", value="600 123 4567")]

    async def get_fallback_email(session, scope):
        return "contacto@autofin.cl"

    monkeypatch.setattr(strategies, "load_schedule", load_schedule)
    monkeypatch.setattr(strategies, "get_official_channels", get_official_channels)
    monkeypatch.setattr(strategies, "get_fallback_email", get_fallback_email)


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
async def test_internal_envia_correo_al_responsable_del_area():
    mailer = FakeMailer()

    reply = await InternalStrategy(SESSION, mailer).on_no_answer(CONTEXT)

    to, _, body = mailer.sent[0]
    assert to == ["rrhh@autofin.cl"]
    assert "¿Cuándo pagan el bono?" in body and "Ana Pérez" in body and "ana@autofin.cl" in body
    assert "te contactará a la brevedad" in reply.text


@pytest.mark.anyio
async def test_internal_sin_area_envia_correo_a_la_direccion_general():
    mailer = FakeMailer()

    await InternalStrategy(SESSION, mailer).on_no_answer(NoAnswerContext("¿Dónde está el casino?", [], "Ana Pérez", "ana@autofin.cl"))

    assert mailer.sent[0][0] == ["contacto@autofin.cl"]


@pytest.mark.anyio
async def test_internal_si_falla_el_correo_lo_registra_y_pide_contactar_al_area(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.ERROR)

    reply = await InternalStrategy(SESSION, FakeMailer(fail=True)).on_no_answer(CONTEXT)

    assert "No se pudo enviar el correo" in caplog.text
    assert "contacta directamente" in reply.text
