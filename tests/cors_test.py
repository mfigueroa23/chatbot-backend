from typing import Any, cast
import pytest
from sqlalchemy import DefaultClause, String, Table, UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.cors_origins import CorsOrigin
from src.services.cors import is_origin_allowed
from src.utils.exceptions.database import DatabaseUnavailableError

TABLE = cast(Table, CorsOrigin.__table__)


class FakeResult:
    def __init__(self, value: int | None):
        self.value = value

    def scalar_one_or_none(self) -> int | None:
        return self.value


class FakeSession:
    def __init__(self, value: int | None):
        self.value = value
        self.statements: list[Any] = []

    async def execute(self, statement):
        self.statements.append(statement)
        return FakeResult(self.value)


class DownSession:
    async def execute(self, statement):
        raise ConnectionRefusedError()


def test_cors_origin_tiene_origen_unico_y_no_nulo():
    unique = [c for c in TABLE.constraints if isinstance(c, UniqueConstraint) and c.name == "uq_cors_origins_origin"]
    origin = TABLE.c.origin

    assert TABLE.name == "cors_origins"
    assert origin.nullable is False
    assert isinstance(origin.type, String) and origin.type.length == 255
    assert len(unique) == 1
    assert [column.name for column in unique[0].columns] == ["origin"]


def test_cors_origin_esta_habilitado_por_defecto_en_la_base_de_datos():
    enabled = TABLE.c.enabled

    assert enabled.nullable is False
    assert isinstance(enabled.server_default, DefaultClause)
    assert str(enabled.server_default.arg) == "true"


@pytest.mark.anyio
async def test_is_origin_allowed_es_true_si_el_origen_esta_registrado_y_habilitado():
    assert await is_origin_allowed(cast(AsyncSession, FakeSession(1)), "https://app.ejemplo.com") is True


@pytest.mark.anyio
async def test_is_origin_allowed_es_false_si_no_hay_fila():
    assert await is_origin_allowed(cast(AsyncSession, FakeSession(None)), "https://otro.ejemplo.com") is False


@pytest.mark.anyio
async def test_is_origin_allowed_filtra_por_el_origen_exacto_y_habilitado():
    session = FakeSession(None)

    await is_origin_allowed(cast(AsyncSession, session), "HTTPS://App.Ejemplo.com:443/")

    compiled = session.statements[0].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert len(session.statements) == 1
    assert "cors_origins.origin = " in sql
    assert "cors_origins.enabled IS true" in sql
    assert list(compiled.params.values()) == ["HTTPS://App.Ejemplo.com:443/"]


@pytest.mark.anyio
async def test_is_origin_allowed_lanza_database_unavailable_si_la_bd_esta_caida():
    with pytest.raises(DatabaseUnavailableError):
        await is_origin_allowed(cast(AsyncSession, DownSession()), "https://app.ejemplo.com")
