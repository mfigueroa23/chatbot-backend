from typing import cast
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.business_area import AreaScope
from src.agents.graph import load_catalog
from src.services.business_data import AreaTopics, get_area_topics, get_areas, get_fallback_space


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


class Topic:
    def __init__(self, area_id: int, label: str):
        self.area_id, self.label = area_id, label


class CatalogSession:
    """Áreas activas, FAQ y procedimientos por execute; textos de agent_prompt y properties por key en scalar."""

    def __init__(self, areas: list[Area], prompts: dict[str, str], faqs: list[Topic] | None = None,
                 procedures: list[Topic] | None = None):
        self.areas = areas
        self.prompts = prompts
        self.faqs = faqs or []
        self.procedures = procedures or []
        self.statements: list = []

    async def execute(self, statement):
        self.statements.append(statement)
        sql = compiled(statement)
        if sql.startswith("SELECT faq."):
            return list(self.faqs)
        if sql.startswith("SELECT procedure."):
            return list(self.procedures)
        return AreasResult(self.areas)

    async def scalar(self, statement):
        (key,) = statement.compile().params.values()
        return self.prompts.get(key)


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



# --- Spec 004: temas del agente de ámbito y prompts del coordinador ------------------------------------------------

@pytest.mark.anyio
async def test_get_area_topics_agrupa_por_area_sin_respuestas_y_con_tope():
    faqs = [Topic(1, "¿Cómo pago?"), Topic(1, "¿Dónde veo mi saldo?"), Topic(1, "¿Puedo prepagar?"), Topic(2, "¿Cubre robo?")]
    session = CatalogSession([], {}, faqs, [Topic(1, "Copia del contrato")])

    topics = await get_area_topics(cast(AsyncSession, session), [1, 2], limit=2)

    assert topics == {1: AreaTopics(["¿Cómo pago?", "¿Dónde veo mi saldo?"], ["Copia del contrato"]),
                      2: AreaTopics(["¿Cubre robo?"], [])}
    faq_sql, procedure_sql = (compiled(statement) for statement in session.statements)
    assert "faq.active" in faq_sql and "business_area.active" in faq_sql and "faq.answer" not in faq_sql
    assert "procedure.active" in procedure_sql and "procedure.steps" not in procedure_sql


@pytest.mark.anyio
async def test_get_area_topics_sin_areas_no_consulta():
    session = CatalogSession([], {})

    assert await get_area_topics(cast(AsyncSession, session), [], limit=50) == {}
    assert session.statements == []


@pytest.mark.anyio
async def test_load_catalog_lee_los_prompts_del_coordinador_y_del_ambito_con_temas():
    session = CatalogSession(
        [Area(1, "Pagos", "Prompt de Pagos")],
        {"external_coordinator": "Coordinador", "external_agent": "Ámbito", "area_rules": "Reglas",
         "scope_topics_per_area": "1"},
        [Topic(1, "¿Cómo pago?"), Topic(1, "¿Saldo?")],
    )

    catalog = await load_catalog(cast(AsyncSession, session), AreaScope.external)

    assert (catalog.coordinator_prompt, catalog.scope_prompt) == ("Coordinador", "Ámbito")
    assert catalog.topics == {1: AreaTopics(["¿Cómo pago?"], [])}


@pytest.mark.anyio
async def test_load_catalog_sin_prompt_del_coordinador_lo_deja_vacio():
    session = CatalogSession([Area(1, "Pagos", "Prompt de Pagos")], {})

    catalog = await load_catalog(cast(AsyncSession, session), AreaScope.internal)

    assert (catalog.coordinator_prompt, catalog.scope_prompt) == ("", "")


@pytest.mark.anyio
@pytest.mark.parametrize(("scope", "expected"), [(AreaScope.external, ["Pagos"]), (AreaScope.internal, [])])
async def test_load_catalog_el_web_conoce_los_nombres_internos_para_prohibirlos(scope: AreaScope, expected: list[str]):
    session = CatalogSession([Area(1, "Pagos", "Prompt de Pagos")], {})

    catalog = await load_catalog(cast(AsyncSession, session), scope)

    assert catalog.other_area_names == expected
    if scope == AreaScope.external:
        assert "business_area.scope = 'internal'" in compiled(session.statements[-1])
