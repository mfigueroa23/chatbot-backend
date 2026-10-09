import logging
from types import SimpleNamespace
from typing import Any, cast
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.llm import Embedder, FaqHit, Subtask
from src.models.business_area import AreaScope, BusinessArea
from src.models.faq_category import FaqCategory
from src.services.knowledge import FaqRow, PgKnowledge, build_catalog, pending_faqs

AREAS = [
    BusinessArea(id=2, name="Ventas", description="Créditos", scope=AreaScope.external, system_prompt="Eres Ventas.",
                 tools=["tasa_del_dia"], active=True),
    BusinessArea(id=1, name="Servicio al Cliente", description="Pagos", scope=AreaScope.external, system_prompt=None,
                 tools=[], active=True),
    BusinessArea(id=3, name="Seguros", description="Siniestros", scope=AreaScope.external, system_prompt="x",
                 tools=[], active=False),
    BusinessArea(id=10, name="Personas", description="Bonos", scope=AreaScope.internal, system_prompt="x",
                 tools=[], active=True),
]
CATEGORIES = [FaqCategory(area_id=1, name="Seguros"), FaqCategory(area_id=1, name="Pagos"),
              FaqCategory(area_id=10, name="Bonos")]
PROMPTS = {"external_coordinator": "Coordinador externo.", "internal_coordinator": "Coordinador interno.",
           "sub_agent_rules": "Reglas."}


def test_catalog_solo_tiene_las_areas_activas_del_canal_con_sus_categorias():
    catalog = build_catalog(AREAS, CATEGORIES, PROMPTS, AreaScope.external)

    service, sales = catalog.areas
    assert (service.name, sales.name) == ("Servicio al Cliente", "Ventas")
    assert service.categories == ("Pagos", "Seguros") and service.system_prompt == ""
    assert sales.tools == ("tasa_del_dia",)
    assert catalog.area(3) is None and catalog.area(10) is None


def test_catalog_toma_el_prompt_del_coordinador_de_su_canal():
    internal = build_catalog(AREAS, CATEGORIES, PROMPTS, AreaScope.internal)

    assert internal.coordinator_prompt == "Coordinador interno." and internal.sub_agent_rules == "Reglas."
    assert [area.name for area in internal.areas] == ["Personas"]


def test_catalog_avisa_si_falta_un_prompt(caplog):
    with caplog.at_level(logging.WARNING, logger="src"):
        catalog = build_catalog(AREAS, CATEGORIES, {}, AreaScope.external)

    assert catalog.coordinator_prompt == "" and "external_coordinator" in caplog.text


def test_pending_solo_elige_las_faq_nuevas_o_editadas():
    rows = [FaqRow(1, "¿Nueva?", "Sí", "h1", None),
            FaqRow(2, "¿Editada?", "Sí", "h2-nuevo", "h2-viejo"),
            FaqRow(3, "¿Igual?", "Sí", "h3", "h3")]

    assert [row.id for row in pending_faqs(rows)] == [1, 2]


class RecordingSession:
    """Sesión falsa de PgKnowledge: registra el orden de las sentencias y devuelve una FAQ pendiente."""

    def __init__(self, log: list[str]):
        self.log = log

    async def execute(self, statement):
        sql = str(statement.compile(dialect=postgresql.dialect()))
        if sql.startswith("UPDATE"):
            self.log.append("guardar embedding")
            return []
        if "IS DISTINCT FROM" in sql:
            self.log.append("buscar pendientes")
            return [SimpleNamespace(id=7, question="¿Cómo pago?", answer="En la web.", content_hash="h", embedded_hash=None)]
        self.log.append("buscar FAQ parecidas")
        return [SimpleNamespace(id=7, name="Pagos", question="¿Cómo pago?", answer="En la web.")]

    async def commit(self):
        self.log.append("commit")


class RecordingEmbedder(Embedder):
    def __init__(self, log: list[str]):
        self.log = log

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.log.append(f"embed {texts}")
        return [[0.1] * 3 for _ in texts]


@pytest.mark.anyio
async def test_sync_genera_los_embeddings_pendientes_antes_de_buscar():
    log: list[str] = []
    knowledge = PgKnowledge(cast(AsyncSession, cast(Any, RecordingSession(log))), RecordingEmbedder(log))

    hits = await knowledge.search([Subtask(1, "pagar cuota")], 5)

    assert log == ["buscar pendientes", "embed ['¿Cómo pago?\\nEn la web.']", "guardar embedding", "commit",
                   "embed ['pagar cuota']", "buscar FAQ parecidas"]
    assert hits == {1: [FaqHit(7, "Pagos", "¿Cómo pago?", "En la web.")]}
