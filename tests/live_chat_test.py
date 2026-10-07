from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import cast
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.live_chat import CloseReason, LiveChat, LiveChatStatus
from src.services.live_chat import (
    close_by_executive, customer_left, enqueue, executive_left, executive_timed_out, resume_chat, take, take_chat)
from src.utils.exceptions.live_chat import ChatAlreadyAssignedError, ExecutiveChatLimitError, NotChatOwnerError
from tests.fakes import FakeClock, web_session

SESSION_ID = web_session().id


class EnqueueSession:
    def __init__(self, existing: LiveChat | None = None):
        self.existing = existing
        self.added = []

    def add(self, item):
        self.added.append(item)

    @asynccontextmanager
    async def begin_nested(self):
        yield

    async def flush(self):
        if self.existing is not None:
            raise IntegrityError("INSERT", {}, Exception("ux_live_chat_open_web_session"))

    async def scalar(self, statement):
        return self.existing


@pytest.mark.anyio
async def test_enqueue_crea_un_chat_en_espera():
    session = EnqueueSession()

    chat = await enqueue(cast(AsyncSession, session), SESSION_ID, "Ana", "ana@correo.cl", "¿Cheque?")

    assert chat.status == LiveChatStatus.waiting
    assert session.added == [chat]


@pytest.mark.anyio
async def test_enqueue_devuelve_el_chat_abierto_si_ya_existe():
    existing = LiveChat(id=7, web_session_id=SESSION_ID, status=LiveChatStatus.waiting)

    chat = await enqueue(cast(AsyncSession, EnqueueSession(existing)), SESSION_ID, "Ana", "ana@correo.cl", "¿Cheque?")

    assert chat is existing


# --- Dominio ------------------------------------------------------------------------------------------------------

NOW = datetime(2026, 10, 7, 15, tzinfo=UTC)
WINDOW = timedelta(minutes=60)


def waiting_chat() -> LiveChat:
    return LiveChat(id=1, web_session_id=SESSION_ID, status=LiveChatStatus.waiting, executive_id=None,
                    executive_disconnected_at=None, customer_name="Ana", customer_contact="ana@correo.cl",
                    pending_question="¿Cheque?")


def test_domain_tomar_asigna_el_chat_en_exclusiva():
    chat = waiting_chat()

    take_chat(chat, executive_id=5, assigned_count=0, max_chats=3, now=NOW)

    assert (chat.status, chat.executive_id, chat.assigned_at) == (LiveChatStatus.assigned, 5, NOW)
    with pytest.raises(ChatAlreadyAssignedError):
        take_chat(chat, executive_id=6, assigned_count=0, max_chats=3, now=NOW)


def test_domain_no_se_supera_el_maximo_de_chats_del_ejecutivo():
    with pytest.raises(ExecutiveChatLimitError):
        take_chat(waiting_chat(), executive_id=5, assigned_count=3, max_chats=3, now=NOW)


def test_domain_el_ejecutivo_retoma_antes_de_60_minutos():
    clock = FakeClock(NOW)
    chat = waiting_chat()
    take_chat(chat, 5, 0, 3, clock.now())
    executive_left(chat, clock.now())

    clock.advance(timedelta(minutes=59))

    assert not executive_timed_out(chat, clock.now(), WINDOW)
    assert resume_chat(chat, clock.now(), WINDOW)
    assert chat.executive_disconnected_at is None


def test_domain_vence_el_plazo_a_los_60_minutos():
    clock = FakeClock(NOW)
    chat = waiting_chat()
    take_chat(chat, 5, 0, 3, clock.now())
    executive_left(chat, clock.now())

    clock.advance(timedelta(minutes=60))

    assert executive_timed_out(chat, clock.now(), WINDOW)
    assert not resume_chat(chat, clock.now(), WINDOW)


def test_domain_la_salida_del_cliente_cierra_el_chat_en_espera_o_asignado():
    waiting = waiting_chat()
    assigned = waiting_chat()
    take_chat(assigned, 5, 0, 3, NOW)

    customer_left(waiting, NOW)
    customer_left(assigned, NOW)

    assert [(c.status, c.close_reason) for c in (waiting, assigned)] == [
        (LiveChatStatus.closed, CloseReason.customer_left)] * 2


def test_domain_solo_el_ejecutivo_asignado_puede_cerrar():
    chat = waiting_chat()
    take_chat(chat, 5, 0, 3, NOW)

    with pytest.raises(NotChatOwnerError):
        close_by_executive(chat, executive_id=6, now=NOW)
    close_by_executive(chat, executive_id=5, now=NOW)

    assert (chat.status, chat.close_reason, chat.closed_at) == (LiveChatStatus.closed, CloseReason.executive, NOW)


# --- SQL ----------------------------------------------------------------------------------------------------------

class TakeSession:
    def __init__(self, assigned_count: int, taken: LiveChat | None):
        self.results = [assigned_count, taken]
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)

    async def scalar(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)


def sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


@pytest.mark.anyio
async def test_sql_take_bloquea_al_ejecutivo_y_solo_actualiza_chats_en_espera():
    taken = waiting_chat()
    session = TakeSession(0, taken)

    chat = await take(cast(AsyncSession, session), 1, 5, 3, NOW)

    assert chat is taken
    assert "FOR UPDATE" in sql(session.statements[0])
    update_statement = next(s for s in session.statements if sql(s).startswith("UPDATE live_chat"))
    where = sql(update_statement).split("WHERE", 1)[1]
    assert "live_chat.status = %(status_1)s" in where
    assert update_statement.compile(dialect=postgresql.dialect()).params["status_1"] == LiveChatStatus.waiting


@pytest.mark.anyio
async def test_sql_take_con_el_maximo_alcanzado_no_actualiza():
    session = TakeSession(3, None)

    with pytest.raises(ExecutiveChatLimitError):
        await take(cast(AsyncSession, session), 1, 5, 3, NOW)

    assert not any(sql(s).startswith("UPDATE") for s in session.statements)
