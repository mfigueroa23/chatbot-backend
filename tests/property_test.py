import logging
from typing import Any, cast
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.property import Properties, get_property, load_properties
from src.utils.exceptions.database import DatabaseUnavailableError
from src.utils.exceptions.property import PropertyNotFoundError
from tests.fakes import PropertySession


def as_session(fake: PropertySession) -> AsyncSession:
    return cast(AsyncSession, cast(Any, fake))


@pytest.mark.anyio
async def test_get_property_consulta_la_tabla_en_cada_llamada():
    fake = PropertySession({"faqs_per_search": "5"})

    assert await get_property(as_session(fake), "faqs_per_search") == "5"
    fake.values["faqs_per_search"] = "8"

    assert await get_property(as_session(fake), "faqs_per_search") == "8"
    assert fake.queries == 2


@pytest.mark.anyio
async def test_get_property_lanza_error_si_no_existe():
    with pytest.raises(PropertyNotFoundError):
        await get_property(as_session(PropertySession({})), "gemini_api_key")


@pytest.mark.anyio
async def test_load_properties_trae_todo_en_una_consulta():
    fake = PropertySession({"faqs_per_search": "5", "coordinator_model": "flash"})

    properties = await load_properties(as_session(fake))

    assert properties.values == {"faqs_per_search": "5", "coordinator_model": "flash"}
    assert fake.queries == 1


@pytest.mark.anyio
@pytest.mark.parametrize("call", [
    lambda session: get_property(session, "faqs_per_search"),
    lambda session: load_properties(session),
])
async def test_base_de_datos_caida_lanza_database_unavailable(call):
    with pytest.raises(DatabaseUnavailableError):
        await call(as_session(PropertySession({}, down=True)))


def test_required_lanza_error_si_falta():
    with pytest.raises(PropertyNotFoundError):
        Properties({}).required("gemini_api_key")


def test_get_int_usa_el_valor_o_el_default(caplog):
    properties = Properties({"faqs_per_search": "8", "history_messages": "diez"})

    with caplog.at_level(logging.WARNING, logger="src"):
        assert properties.get_int("faqs_per_search", 5) == 8
        assert properties.get_int("max_areas_per_message", 3) == 3
        assert properties.get_int("history_messages", 10) == 10

    assert "history_messages" in caplog.text and "diez" not in caplog.text
