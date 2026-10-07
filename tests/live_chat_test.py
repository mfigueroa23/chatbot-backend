from contextlib import asynccontextmanager
from typing import cast
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.live_chat import LiveChat, LiveChatStatus
from src.services.live_chat import enqueue
from tests.fakes import web_session

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
