from typing import cast
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.retriever import FaqRetriever
from src.models.business_area import AreaScope
from src.models.faq import Faq
from src.models.procedure import Procedure
from src.models.procedure_field import FieldKind, ProcedureField
from tests.fakes import FakeEmbedder


class Row:
    def __init__(self, **values):
        self.__dict__.update(values)


class Result:
    def __init__(self, items: list):
        self.items = items

    def __iter__(self):
        return iter(self.items)

    def scalars(self):
        return self.items


class ScopeSession:
    """Devuelve un resultado por consulta, en orden, para execute y para scalar."""

    def __init__(self, executes: list[list], scalars: list | None = None):
        self.executes = list(executes)
        self.scalars = list(scalars or [])
        self.statements = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def execute(self, statement):
        self.statements.append(statement)
        return Result(self.executes.pop(0) if self.executes else [])

    async def scalar(self, statement):
        self.statements.append(statement)
        return self.scalars.pop(0) if self.scalars else None

    async def commit(self):
        self.committed = True


def retriever_with(session: ScopeSession, embedder: FakeEmbedder) -> FaqRetriever:
    return FaqRetriever(lambda: cast(AsyncSession, session), embedder, top_k=4, min_similarity=0.75)


def sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False}))


FAQ_ROW = Row(id=11, question="¿Plazo?", answer="48 meses", area_id=1, distance=0.1)
PROCEDURE_ROW = Row(id=7, name="Copia del contrato", steps="Se envía al correo", area_id=1, distance=0.2)
RUT = ProcedureField(procedure_id=7, name="rut", label="RUT del titular", kind=FieldKind.rut, position=0)


@pytest.mark.anyio
async def test_scope_busca_faq_y_procedimientos_del_ambito_con_un_solo_embedding():
    session = ScopeSession([[FAQ_ROW], [PROCEDURE_ROW], [RUT]], scalars=[0.5, None])
    embedder = FakeEmbedder()

    knowledge = await retriever_with(session, embedder).search_scope(AreaScope.external, "¿Cuántos meses?")

    assert embedder.queries == ["¿Cuántos meses?"]
    faq_sql, procedure_sql = sql(session.statements[0]), sql(session.statements[1])
    for statement in (faq_sql, procedure_sql):
        where = statement.split("WHERE", 1)[1]
        assert "business_area.scope = %(scope_1)s" in where and "business_area.active" in where
    assert "faq.active" in faq_sql and "procedure.active" in procedure_sql
    assert "(faq.embedding <=> %(embedding_1)s) <= %(param_1)s" in faq_sql
    assert [(hit.id, hit.area_id, round(hit.similarity, 2)) for hit in knowledge.faqs] == [(11, 1, 0.9)]
    assert [(p.id, p.area_id, [f.name for f in p.fields]) for p in knowledge.procedures] == [(7, 1, ["rut"])]


@pytest.mark.anyio
async def test_scope_calcula_la_mejor_similitud_del_otro_ambito_sin_su_contenido():
    match = ScopeSession([[FAQ_ROW], []], scalars=[0.2, 0.4])
    no_match = ScopeSession([[FAQ_ROW], []], scalars=[0.5, None])

    assert (await retriever_with(match, FakeEmbedder()).search_scope(AreaScope.external, "x")).other_scope_match
    assert not (await retriever_with(no_match, FakeEmbedder()).search_scope(AreaScope.external, "x")).other_scope_match
    other_sql = sql(match.statements[2])
    assert "min(" in other_sql.lower() and "business_area.scope = %(scope_1)s" in other_sql
    assert match.statements[2].compile(dialect=postgresql.dialect()).params["scope_1"] == AreaScope.internal


@pytest.mark.anyio
async def test_refresh_solo_recalcula_las_faq_desactualizadas():
    stale = Faq(id=1, question="¿Plazo?", answer="48 meses", content_hash="abc", embedded_hash=None)
    session = ScopeSession([[stale], []])
    embedder = FakeEmbedder()

    await retriever_with(session, embedder).refresh_stale_embeddings([3])

    assert "faq.embedded_hash IS DISTINCT FROM faq.content_hash" in sql(session.statements[0])
    assert embedder.documents == ["¿Plazo?\n48 meses"]
    assert stale.embedded_hash == "abc" and stale.embedding == [0.2] * 768
    assert session.committed


@pytest.mark.anyio
async def test_refresh_recalcula_tambien_los_procedimientos_desactualizados():
    stale = Procedure(id=5, name="Copia del contrato", steps="El área la envía", content_hash="xyz", embedded_hash=None)
    session = ScopeSession([[], [stale]])
    embedder = FakeEmbedder()

    await retriever_with(session, embedder).refresh_stale_embeddings([3])

    assert "procedure.embedded_hash IS DISTINCT FROM procedure.content_hash" in sql(session.statements[1])
    assert embedder.documents == ["Copia del contrato\nEl área la envía"]
    assert stale.embedded_hash == "xyz"
