import asyncio
import logging
from typing import Any, cast
import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.interfaces.google_chat import AddonEvent, chat_reply
from src.services import google_chat_reply
from src.services.google_chat_reply import AVISO, DEMORA, NO_DISPONIBLE, answer, pending, process, read_thresholds
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


def dm_event() -> AddonEvent:
    return AddonEvent.model_validate({"chat": {"messagePayload": {
        "space": {"name": "spaces/DM1", "spaceType": "DIRECT_MESSAGE"},
        "message": {"text": "¿cómo pago?", "thread": {"name": "spaces/DM1/threads/X9"},
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


def asking(release: asyncio.Event | None = None):
    """ask falso: responde "ok" en cuanto se libera el evento (o de inmediato si no hay evento)."""
    async def fake_ask(*args):
        if release is not None:
            await release.wait()
        return "ok"
    return fake_ask


@pytest.fixture
def published(monkeypatch) -> list[tuple[str, str]]:
    """Sustituye la cuenta de servicio y la publicación en Chat; devuelve los mensajes publicados."""
    calls: list[tuple[str, str]] = []

    async def fake_chat_token(session, http):
        return "ya29.token"

    async def fake_create_message(space, text, token, http):
        calls.append((space, text))

    monkeypatch.setattr(google_chat_reply, "chat_token", fake_chat_token)
    monkeypatch.setattr(google_chat_reply, "create_message", fake_create_message)
    return calls


async def delivered() -> None:
    await asyncio.gather(*pending)
    await asyncio.sleep(0)


@pytest.mark.anyio
async def test_answer_responde_en_el_hilo_si_termina_antes_del_aviso(monkeypatch, published):
    monkeypatch.setattr(google_chat_reply, "ask", asking())

    assert await answer(GRAPH, space_event(), 0.5, 1) == chat_reply("ok")
    assert published == []
    assert not pending


@pytest.mark.anyio
@pytest.mark.parametrize("event, expected", [
    (space_event, ("spaces/AAA", "<users/123> ok")),
    (dm_event, ("spaces/DM1", "ok")),
])
async def test_answer_avisa_y_publica_la_respuesta_como_mensaje_nuevo(monkeypatch, published, event, expected):
    release = asyncio.Event()
    monkeypatch.setattr(google_chat_reply, "ask", asking(release))

    assert await answer(GRAPH, event(), 0.01, 1) == chat_reply(AVISO)
    release.set()
    await delivered()

    assert published == [expected]
    assert not pending


@pytest.mark.anyio
async def test_answer_registra_error_y_no_reintenta_si_falla_la_publicacion(monkeypatch, caplog):
    release = asyncio.Event()
    calls: list[str] = []

    async def fake_chat_token(session, http):
        return "ya29.token"

    async def failing_create_message(space, text, token, http):
        calls.append(text)
        raise httpx.HTTPError("403")

    monkeypatch.setattr(google_chat_reply, "ask", asking(release))
    monkeypatch.setattr(google_chat_reply, "chat_token", fake_chat_token)
    monkeypatch.setattr(google_chat_reply, "create_message", failing_create_message)

    assert await answer(GRAPH, space_event(), 0.01, 1) == chat_reply(AVISO)
    release.set()
    await delivered()

    assert calls == ["<users/123> ok"]
    assert any(record.levelno == logging.ERROR for record in caplog.records)
    assert not pending


@pytest.mark.anyio
@pytest.mark.parametrize("notice, maximum", [(0.02, 0.02), (0.05, 0.01)])
async def test_answer_nunca_avisa_si_el_aviso_no_es_menor_que_el_maximo(monkeypatch, published, notice, maximum):
    monkeypatch.setattr(google_chat_reply, "ask", asking(asyncio.Event()))

    assert await answer(GRAPH, space_event(), notice, maximum) == chat_reply(DEMORA)
    assert published == []
    assert not pending


@pytest.mark.anyio
async def test_answer_atiende_por_separado_dos_mensajes_de_la_misma_conversacion(monkeypatch, published):
    release = asyncio.Event()
    monkeypatch.setattr(google_chat_reply, "ask", asking(release))

    assert await answer(GRAPH, space_event(), 0.01, 1) == chat_reply(AVISO)
    assert await answer(GRAPH, space_event(), 0.01, 1) == chat_reply(AVISO)
    release.set()
    await delivered()

    assert published == [("spaces/AAA", "<users/123> ok"), ("spaces/AAA", "<users/123> ok")]
    assert not pending
