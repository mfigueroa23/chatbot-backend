import asyncio
from typing import Any, cast
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.interfaces.google_chat import AddonEvent
from src.services import google_chat_reply
from src.services.google_chat_reply import DEMORA, NO_DISPONIBLE, process, read_thresholds
from src.utils.exceptions.agents import AgentNotFoundError
from src.utils.exceptions.database import DatabaseUnavailableError
from src.utils.exceptions.property import PropertyNotFoundError

GRAPH = cast(Any, object())
SESSION = cast(AsyncSession, None)


def space_event() -> AddonEvent:
    return AddonEvent.model_validate({"chat": {"messagePayload": {
        "space": {"name": "spaces/AAA", "spaceType": "SPACE"},
        "message": {"text": "@Asistente ¿cómo pago?", "argumentText": " ¿cómo pago?",
                    "thread": {"name": "spaces/AAA/threads/T1"},
                    "sender": {"name": "users/123", "type": "HUMAN"}}}}})


@pytest.mark.anyio
async def test_process_devuelve_la_respuesta_con_el_hilo_del_mensaje_original(monkeypatch):
    calls: list[str] = []

    async def fake_ask(graph, session, coordinator, audiencia, thread_id, mensaje):
        calls.append(thread_id)
        return "ok"

    monkeypatch.setattr(google_chat_reply, "ask", fake_ask)

    assert await process(GRAPH, space_event(), 1) == "ok"
    assert calls == ["spaces/AAA/threads/T1"]


@pytest.mark.anyio
@pytest.mark.parametrize("error", [AgentNotFoundError("Agente Interno"), DatabaseUnavailableError("sin conexión")])
async def test_process_devuelve_no_disponible_si_falla_el_agente_o_la_bd(monkeypatch, error):
    async def fake_ask(*args):
        raise error

    monkeypatch.setattr(google_chat_reply, "ask", fake_ask)

    assert await process(GRAPH, space_event(), 1) == NO_DISPONIBLE


@pytest.mark.anyio
async def test_process_devuelve_demora_y_cancela_ask_al_pasar_el_maximo(monkeypatch):
    cancelled = asyncio.Event()

    async def blocked_ask(*args):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(google_chat_reply, "ask", blocked_ask)

    assert await process(GRAPH, space_event(), 0.01) == DEMORA
    assert cancelled.is_set()


def fake_properties(monkeypatch, values: dict[str, str]) -> None:
    async def fake_get_property(session, key):
        if key not in values:
            raise PropertyNotFoundError(key)
        return values[key]

    monkeypatch.setattr(google_chat_reply, "get_property", fake_get_property)


@pytest.mark.anyio
async def test_read_thresholds_lee_el_aviso_y_el_maximo(monkeypatch):
    fake_properties(monkeypatch, {"google_chat_notice_seconds": "5", "google_timeout": "120"})

    assert await read_thresholds(SESSION) == (5, 120)


@pytest.mark.anyio
async def test_read_thresholds_usa_10_segundos_si_falta_el_aviso(monkeypatch):
    fake_properties(monkeypatch, {"google_timeout": "120"})

    assert await read_thresholds(SESSION) == (10, 120)


@pytest.mark.anyio
async def test_read_thresholds_lanza_error_si_falta_el_maximo(monkeypatch):
    fake_properties(monkeypatch, {"google_chat_notice_seconds": "5"})

    with pytest.raises(PropertyNotFoundError):
        await read_thresholds(SESSION)
