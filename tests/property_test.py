from typing import cast
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from src.services import property as property_service
from src.services.property import get_float_property, get_int_property, get_str_property
from src.utils.exceptions.property import PropertyNotFoundError


class Row:
    def __init__(self, key: str, value: str):
        self.key = key
        self.value = value


class PropertySession:
    def __init__(self, values: dict[str, str]):
        self.values = values

    async def execute(self, statement):
        return [Row(key, value) for key, value in self.values.items()]


def session_with(values: dict[str, str]) -> AsyncSession:
    return cast(AsyncSession, PropertySession(values))


@pytest.fixture(autouse=True)
def reset_cache():
    property_service._loaded_at = None
    yield
    property_service._loaded_at = None


@pytest.mark.anyio
async def test_devuelve_el_valor_presente_con_su_tipo():
    session = session_with({"rag_top_k": "6", "rag_min_similarity": "0.8", "gemini_model": "flash"})

    assert await get_int_property(session, "rag_top_k", 4) == 6
    assert await get_float_property(session, "rag_min_similarity", 0.75) == 0.8
    assert await get_str_property(session, "gemini_model") == "flash"


@pytest.mark.anyio
async def test_devuelve_el_default_si_la_property_no_existe():
    session = session_with({})

    assert await get_int_property(session, "rag_top_k", 4) == 4
    assert await get_float_property(session, "rag_min_similarity", 0.75) == 0.75
    assert await get_str_property(session, "gemini_model", "flash") == "flash"


@pytest.mark.anyio
async def test_lanza_error_si_no_existe_y_no_hay_default():
    with pytest.raises(PropertyNotFoundError):
        await get_int_property(session_with({}), "rag_top_k")


@pytest.mark.anyio
async def test_lanza_error_si_el_valor_no_es_numerico():
    with pytest.raises(ValueError):
        await get_int_property(session_with({"rag_top_k": "cuatro"}), "rag_top_k", 4)
