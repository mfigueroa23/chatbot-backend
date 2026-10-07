from typing import cast
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.retriever import FaqRetriever
from src.models.faq import Faq
from src.models.procedure import Procedure
from src.models.procedure_field import FieldKind, ProcedureField
from tests.fakes import FakeEmbedder


class Row:
    def __init__(self, question: str, answer: str, distance: float):
        self.question = question
        self.answer = answer
        self.distance = distance


class Result:
    def __init__(self, items: list):
        self.items = items

    def __iter__(self):
        return iter(self.items)

    def scalars(self):
        return self.items


class FaqSession:
    """Devuelve un resultado por consulta, en orden; el último se repite."""

    def __init__(self, *results: list):
        self.results = list(results)
        self.statements = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def execute(self, statement):
        self.statements.append(statement)
        return Result(self.results.pop(0) if len(self.results) > 1 else self.results[0])

    async def commit(self):
        self.committed = True


def retriever_with(session: FaqSession, embedder: FakeEmbedder) -> FaqRetriever:
    return FaqRetriever(lambda: cast(AsyncSession, session), embedder, top_k=4, min_similarity=0.75)


@pytest.mark.anyio
async def test_search_faq_filtra_por_area_ordena_por_distancia_y_aplica_el_umbral():
    session = FaqSession([Row("¿Plazo?", "48 meses", 0.1)])
    embedder = FakeEmbedder()

    hits = await retriever_with(session, embedder).search_faq(3, "¿Cuántos meses?")

    compiled = session.statements[0].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "faq_category.area_id = %(area_id_1)s" in sql
    assert "ORDER BY faq.embedding <=> %(embedding_1)s" in sql
    assert "(faq.embedding <=> %(embedding_1)s) <= %(param_1)s" in sql
    assert compiled.params["area_id_1"] == 3
    assert compiled.params["param_1"] == pytest.approx(0.25)
    assert compiled.params["param_2"] == 4
    assert embedder.queries == ["¿Cuántos meses?"]
    assert hits[0].similarity == pytest.approx(0.9)


@pytest.mark.anyio
async def test_refresh_solo_recalcula_las_faq_desactualizadas():
    stale = Faq(id=1, question="¿Plazo?", answer="48 meses", content_hash="abc", embedded_hash=None)
    session = FaqSession([stale], [])
    embedder = FakeEmbedder()

    await retriever_with(session, embedder).refresh_stale_embeddings([3])

    sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "faq.embedded_hash IS DISTINCT FROM faq.content_hash" in sql
    assert embedder.documents == ["¿Plazo?\n48 meses"]
    assert stale.embedded_hash == "abc"
    assert stale.embedding == [0.2] * 768
    assert session.committed



class ProcedureRow:
    def __init__(self, id: int, name: str, steps: str, distance: float):
        self.id = id
        self.name = name
        self.steps = steps
        self.distance = distance


@pytest.mark.anyio
async def test_search_procedures_filtra_por_area_activo_y_umbral_con_sus_campos():
    fields = [ProcedureField(procedure_id=5, name="rut", label="RUT del titular", kind=FieldKind.rut, position=0)]
    session = FaqSession([ProcedureRow(5, "Copia del contrato", "El área envía la copia por correo", 0.2)], fields)

    hits = await retriever_with(session, FakeEmbedder()).search_procedures(3, "Quiero mi contrato")

    compiled = session.statements[0].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "procedure.area_id = %(area_id_1)s" in sql and compiled.params["area_id_1"] == 3
    assert "procedure.active" in sql.split("WHERE", 1)[1]
    assert "(procedure.embedding <=> %(embedding_1)s) <= %(param_1)s" in sql
    assert "ORDER BY procedure.embedding <=> %(embedding_1)s" in sql
    assert [(hit.id, hit.name, round(hit.similarity, 2)) for hit in hits] == [(5, "Copia del contrato", 0.8)]
    assert [(f.name, f.label, f.kind) for f in hits[0].fields] == [("rut", "RUT del titular", FieldKind.rut)]


@pytest.mark.anyio
async def test_search_procedures_sin_resultados_no_consulta_campos():
    session = FaqSession([])

    assert await retriever_with(session, FakeEmbedder()).search_procedures(3, "Hola") == []
    assert len(session.statements) == 1


@pytest.mark.anyio
async def test_refresh_recalcula_tambien_los_procedimientos_desactualizados():
    stale = Procedure(id=5, name="Copia del contrato", steps="El área la envía", content_hash="xyz", embedded_hash=None)
    session = FaqSession([], [stale])
    embedder = FakeEmbedder()

    await retriever_with(session, embedder).refresh_stale_embeddings([3])

    sql = str(session.statements[1].compile(dialect=postgresql.dialect()))
    assert "procedure.embedded_hash IS DISTINCT FROM procedure.content_hash" in sql
    assert embedder.documents == ["Copia del contrato\nEl área la envía"]
    assert stale.embedded_hash == "xyz"
    assert session.committed
