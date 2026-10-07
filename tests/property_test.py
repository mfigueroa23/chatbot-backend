import pytest
from src.services.property import get_float_property, get_int_property, get_str_property
from src.utils.exceptions.property import PropertyNotFoundError
from tests.fakes import property_session


@pytest.mark.anyio
async def test_devuelve_el_valor_presente_con_su_tipo():
    session = property_session({"rag_top_k": "6", "rag_min_similarity": "0.8", "gemini_model": "flash"})

    assert await get_int_property(session, "rag_top_k", 4) == 6
    assert await get_float_property(session, "rag_min_similarity", 0.75) == 0.8
    assert await get_str_property(session, "gemini_model") == "flash"


@pytest.mark.anyio
async def test_devuelve_el_default_si_la_property_no_existe():
    session = property_session({})

    assert await get_int_property(session, "rag_top_k", 4) == 4
    assert await get_float_property(session, "rag_min_similarity", 0.75) == 0.75
    assert await get_str_property(session, "gemini_model", "flash") == "flash"


@pytest.mark.anyio
async def test_lanza_error_si_no_existe_y_no_hay_default():
    with pytest.raises(PropertyNotFoundError):
        await get_int_property(property_session({}), "rag_top_k")


@pytest.mark.anyio
async def test_lanza_error_si_el_valor_no_es_numerico():
    with pytest.raises(ValueError):
        await get_int_property(property_session({"rag_top_k": "cuatro"}), "rag_top_k", 4)


@pytest.mark.anyio
async def test_un_cambio_en_la_tabla_se_ve_en_la_siguiente_lectura():
    values = {"rag_top_k": "4"}
    session = property_session(values)
    assert await get_int_property(session, "rag_top_k") == 4

    values["rag_top_k"] = "6"

    assert await get_int_property(session, "rag_top_k") == 6
