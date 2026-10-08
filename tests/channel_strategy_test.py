from datetime import UTC, datetime, time
from typing import cast
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents import strategies
from src.agents.llm import AreaInfo
from src.agents.strategies import ExternalStrategy, NoAnswerContext
from src.models.business_area import AreaScope
from src.models.official_channel import OfficialChannel
from tests.fakes import FakeClock

SESSION = cast(AsyncSession, object())
PAYROLL = AreaInfo(10, "Remuneraciones", "Sueldos", AreaScope.internal, "Eres Remuneraciones", "spaces/RRHH")
CONTEXT = NoAnswerContext("¿Cuándo pagan el bono?", [PAYROLL], "Ana Pérez", "ana@autofin.cl")


@pytest.fixture(autouse=True)
def business_data(monkeypatch: pytest.MonkeyPatch):
    async def load_schedule(session):
        return {weekday: (time(9, 0), time(18, 0)) for weekday in range(5)}, set()

    async def get_official_channels(session):
        return [OfficialChannel(label="Teléfono", value="600 123 4567")]

    monkeypatch.setattr(strategies, "load_schedule", load_schedule)
    monkeypatch.setattr(strategies, "get_official_channels", get_official_channels)


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