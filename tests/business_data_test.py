from typing import cast
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.business_area import AreaScope
from src.services.business_data import get_areas, get_fallback_space


class EmptyResult:
    def scalars(self):
        return []


class RecordingSession:
    def __init__(self):
        self.statements = []

    async def scalar(self, statement):
        self.statements.append(statement)
        return "spaces/GENERAL"

    async def execute(self, statement):
        self.statements.append(statement)
        return EmptyResult()


def compiled(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


@pytest.mark.anyio
async def test_get_areas_filtra_por_ambito_y_activas_sin_cache():
    session = RecordingSession()

    await get_areas(cast(AsyncSession, session), AreaScope.external)
    await get_areas(cast(AsyncSession, session), AreaScope.external)

    assert len(session.statements) == 2
    where = compiled(session.statements[0]).split("WHERE", 1)[1]
    assert "business_area.scope = 'external'" in where
    assert "business_area.active" in where


@pytest.mark.anyio
async def test_get_fallback_space_filtra_por_ambito():
    session = RecordingSession()

    space = await get_fallback_space(cast(AsyncSession, session), AreaScope.internal)

    assert space == "spaces/GENERAL"
    assert "fallback_space.scope = 'internal'" in compiled(session.statements[0])
