from datetime import UTC, datetime, timedelta
from typing import cast
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.web_session import WebPhase
from src.services.web_session import admit, answer_offer, start_offer, submit_contact
from tests.fakes import FakeClock, web_session

NOW = datetime(2026, 10, 7, 15, tzinfo=UTC)


def offered():
    session = web_session()
    start_offer(session, "¿Puedo pagar con cheque?")
    return session


def test_aceptar_la_oferta_pide_los_datos_de_contacto():
    session = offered()

    answer_offer(session, accept=True)

    assert session.phase == WebPhase.collecting_contact
    assert session.pending_question == "¿Puedo pagar con cheque?"


def test_rechazar_la_oferta_vuelve_al_bot():
    session = offered()

    answer_offer(session, accept=False)

    assert session.phase == WebPhase.bot
    assert session.pending_question is None


def test_datos_validos_ponen_el_chat_en_cola():
    session = offered()
    answer_offer(session, accept=True)

    result = submit_contact(session, " Ana Pérez ", "ana@correo.cl", None)

    assert result.outcome == "queued"
    assert (result.name, result.contact) == ("Ana Pérez", "ana@correo.cl")
    assert session.phase == WebPhase.queued


@pytest.mark.parametrize("name, email, phone", [("", "ana@correo.cl", None), ("Ana", "ana@", None), ("Ana", None, "12")])
def test_datos_invalidos_tres_veces_muestran_los_canales_oficiales(name: str, email: str | None, phone: str | None):
    session = offered()
    answer_offer(session, accept=True)

    outcomes = [submit_contact(session, name, email, phone).outcome for _ in range(3)]

    assert outcomes == ["retry", "retry", "exhausted"]
    assert session.phase == WebPhase.bot


class AdmissionSession:
    def __init__(self, connected: int):
        self.connected = connected
        self.statements = []
        self.committed = False

    async def execute(self, statement):
        self.statements.append(statement)

    async def scalar(self, statement):
        self.statements.append(statement)
        return self.connected

    async def commit(self):
        self.committed = True

    async def rollback(self):
        pass


def compiled(statement):
    return statement.compile(dialect=postgresql.dialect())


@pytest.mark.anyio
@pytest.mark.parametrize("connected, admitted", [(49, True), (50, False)])
async def test_sql_admit_cuenta_las_conectadas_bajo_advisory_lock(connected: int, admitted: bool):
    session = AdmissionSession(connected)

    result = await admit(cast(AsyncSession, session), FakeClock(NOW), web_session().id, 50)

    assert result is admitted
    assert "pg_advisory_xact_lock" in str(compiled(session.statements[0]))
    count = compiled(session.statements[1])
    assert "web_session.connected" in str(count)
    assert "web_session.last_seen_at > %(last_seen_at_1)s" in str(count)
    assert count.params["last_seen_at_1"] == NOW - timedelta(seconds=90)
    assert session.committed is admitted
