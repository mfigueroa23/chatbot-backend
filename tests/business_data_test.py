from typing import cast
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.business_area import AreaScope
from src.agents.graph import load_catalog
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


class Area:
    def __init__(self, area_id: int, name: str, system_prompt: str | None):
        self.id, self.name, self.description = area_id, name, f"Dudas de {name}"
        self.scope, self.system_prompt, self.chat_space = AreaScope.external, system_prompt, None


class AreasResult:
    def __init__(self, areas: list[Area]):
        self._areas = areas

    def scalars(self):
        return self._areas


class CatalogSession:
    """Áreas activas por execute y textos de agent_prompt por key en scalar."""

    def __init__(self, areas: list[Area], prompts: dict[str, str]):
        self.areas = areas
        self.prompts = prompts

    async def execute(self, statement):
        return AreasResult(self.areas)

    async def scalar(self, statement):
        (key,) = statement.compile().params.values()
        return self.prompts.get(key)


@pytest.mark.anyio
async def test_load_catalog_lee_textos_fijos_y_nombres_de_areas():
    session = CatalogSession(
        [Area(1, "Pagos", "Prompt de Pagos"), Area(2, "Seguros", None)],
        {"external_agent": "Agente", "area_rules": "Reglas", "external_greeting": "¡Hola!", "external_off_topic": "No puedo."},
    )

    catalog = await load_catalog(cast(AsyncSession, session), AreaScope.external)

    assert catalog.fixed == {"greeting": "¡Hola!", "closing": None, "off_topic": "No puedo."}
    # Un área sin prompt no responde, pero sigue siendo un área activa del canal: se nombra en los mensajes fijos.
    assert catalog.area_names == ["Pagos", "Seguros"]


@pytest.mark.anyio
@pytest.mark.parametrize("scope", [AreaScope.internal, AreaScope.external])
async def test_load_catalog_lee_la_persona_de_cada_canal(scope: AreaScope):
    session = CatalogSession([Area(1, "Pagos", "Prompt de Pagos")], {f"{scope}_persona": f"Persona {scope}"})

    catalog = await load_catalog(cast(AsyncSession, session), scope)

    assert catalog.persona == f"Persona {scope}"


@pytest.mark.anyio
async def test_load_catalog_sin_persona_la_deja_vacia():
    session = CatalogSession([Area(1, "Pagos", "Prompt de Pagos")], {"internal_agent": "Agente"})

    catalog = await load_catalog(cast(AsyncSession, session), AreaScope.internal)

    assert catalog.persona is None
