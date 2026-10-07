import uuid
from datetime import UTC, datetime, time, timedelta
from typing import cast
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.live_chat import LiveChatStatus
from src.services import sweeper
from src.services.sweeper import chats_to_close_at_schedule_end, is_expired, is_stale, run_sweep, timed_out_chats
from tests.fakes import FakeClock, FakeHub, assigned_chat, web_session

SLOTS = {weekday: (time(9, 0), time(18, 0)) for weekday in range(5)}
CLOSING_TIME = datetime(2026, 10, 7, 21, tzinfo=UTC)  # miércoles 18:00 en Santiago
WINDOW = timedelta(minutes=60)


def waiting_chat(id: int):
    chat = assigned_chat(id)
    chat.status = LiveChatStatus.waiting
    chat.executive_id = None
    return chat


def test_al_terminar_el_horario_solo_se_cierran_los_chats_en_espera():
    chats = [waiting_chat(1), assigned_chat(2), waiting_chat(3)]

    assert chats_to_close_at_schedule_end(chats, CLOSING_TIME - timedelta(minutes=1), SLOTS, set()) == []
    assert [chat.id for chat in chats_to_close_at_schedule_end(chats, CLOSING_TIME, SLOTS, set())] == [1, 3]


def test_se_cierran_los_chats_con_el_ejecutivo_desconectado_mas_de_60_minutos():
    clock = FakeClock(CLOSING_TIME)
    recent, old = assigned_chat(1), assigned_chat(2)
    recent.executive_disconnected_at = clock.now() - timedelta(minutes=59)
    old.executive_disconnected_at = clock.now() - timedelta(minutes=60)

    assert timed_out_chats([recent, old], clock.now(), WINDOW) == [old]


def test_heartbeat_vencido_a_los_90_segundos():
    clock = FakeClock(CLOSING_TIME)

    assert not is_stale(clock.now() - timedelta(seconds=90), clock.now())
    assert is_stale(clock.now() - timedelta(seconds=91), clock.now())
    assert is_stale(None, clock.now())


def test_la_sesion_caduca_a_los_30_dias_desde_el_ultimo_mensaje():
    clock = FakeClock(CLOSING_TIME)
    session = web_session()
    session.last_message_at = clock.now() - timedelta(days=30) + timedelta(seconds=1)

    assert not is_expired(session, clock.now(), 30)
    clock.advance(timedelta(seconds=1))
    assert is_expired(session, clock.now(), 30)


class LockSession:
    def __init__(self, locked: bool):
        self.locked = locked
        self.statements = []
        self.committed = False

    async def scalar(self, statement):
        self.statements.append(statement)
        return self.locked

    async def execute(self, statement):
        self.statements.append(statement)
        return []

    async def commit(self):
        self.committed = True


class FakeCheckpointer:
    def __init__(self):
        self.deleted: list[str] = []

    async def adelete_thread(self, thread_id: str) -> None:
        self.deleted.append(thread_id)


EXPIRED = [uuid.UUID(int=1), uuid.UUID(int=2)]


@pytest.fixture
def steps(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    steps: list[str] = []

    def step(name: str):
        async def function(*args):
            steps.append(name)
        return function

    async def expired_session_ids(session, now, retention_days):
        return EXPIRED

    monkeypatch.setattr(sweeper, "close_waiting_chats", step("fin de horario"))
    monkeypatch.setattr(sweeper, "close_timed_out_chats", step("plazo del ejecutivo"))
    monkeypatch.setattr(sweeper, "disconnect_stale", step("heartbeats"))
    monkeypatch.setattr(sweeper, "expired_session_ids", expired_session_ids)
    return steps


@pytest.mark.anyio
async def test_runner_sin_el_lock_no_hace_nada(steps: list[str]):
    session = LockSession(locked=False)
    checkpointer = FakeCheckpointer()

    ran = await run_sweep(cast(AsyncSession, session), FakeClock(CLOSING_TIME), FakeHub(), checkpointer)

    assert not ran
    assert steps == [] and checkpointer.deleted == []
    assert len(session.statements) == 1 and not session.committed


@pytest.mark.anyio
async def test_runner_con_el_lock_borra_el_hilo_de_cada_sesion_caducada(steps: list[str]):
    session = LockSession(locked=True)
    checkpointer = FakeCheckpointer()

    ran = await run_sweep(cast(AsyncSession, session), FakeClock(CLOSING_TIME), FakeHub(), checkpointer)

    assert ran
    assert steps == ["fin de horario", "plazo del ejecutivo", "heartbeats"]
    assert checkpointer.deleted == [str(session_id) for session_id in EXPIRED]
    assert session.committed
