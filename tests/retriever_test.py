import logging
from typing import cast
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.retriever import FaqRetriever, read_clarify_similarity
from src.models.business_area import AreaScope
from src.models.faq import Faq
from src.models.procedure import Procedure
from src.models.procedure_field import FieldKind, ProcedureField
from tests.fakes import FakeEmbedder, property_session


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


def clarify_retriever(session: ScopeSession, embedder: FakeEmbedder, clarify: float | None = 0.55) -> FaqRetriever:
    return FaqRetriever(lambda: cast(AsyncSession, session), embedder, top_k=4, min_similarity=0.75,
                        clarify_similarity=clarify)


@pytest.mark.anyio
async def test_read_clarify_similarity_usa_0_55_si_falta():
    assert await read_clarify_similarity(property_session({}), 0.68) == 0.55


@pytest.mark.anyio
@pytest.mark.parametrize("value", ["no-es-numero", "0.68", "0.9"])
async def test_read_clarify_similarity_invalido_o_no_menor_que_el_de_respuesta_devuelve_none(value, caplog):
    caplog.set_level(logging.WARNING, logger="src")

    assert await read_clarify_similarity(property_session({"rag_clarify_similarity": value}), 0.68) is None
    assert "rag_clarify_similarity" in caplog.text


@pytest.mark.anyio
async def test_read_clarify_similarity_valido():
    assert await read_clarify_similarity(property_session({"rag_clarify_similarity": "0.5"}), 0.68) == 0.5


SIGNAL_FAQS = [Row(id=11, label="¿Plazo?", area_id=1, distance=0.1), Row(id=12, label="¿Cuota?", area_id=2, distance=0.35)]
SIGNAL_PROCEDURES = [Row(id=7, label="Copia del contrato", area_id=3, distance=0.4)]


@pytest.mark.anyio
async def test_scope_signals_da_areas_propias_y_otro_ambito_sin_contenido():
    session = ScopeSession([SIGNAL_FAQS, SIGNAL_PROCEDURES], scalars=[0.2, None])
    embedder = FakeEmbedder()

    signals = await clarify_retriever(session, embedder).scope_signals(AreaScope.external, "¿Cuántos meses?")

    assert embedder.queries == ["¿Cuántos meses?"] and signals.embedding == [0.1] * 768
    assert signals.own_area_ids == [1]
    assert signals.other_scope_match
    for statement in session.statements[:2]:
        selected = sql(statement).split("FROM", 1)[0]
        assert "answer" not in selected and "steps" not in selected
        where = sql(statement).split("WHERE", 1)[1]
        assert "business_area.scope = %(scope_1)s" in where and "business_area.active" in where


@pytest.mark.anyio
async def test_scope_signals_candidates_entre_los_dos_umbrales():
    below = Row(id=13, label="Lejana", area_id=1, distance=0.5)
    session = ScopeSession([[*SIGNAL_FAQS, below], SIGNAL_PROCEDURES], scalars=[None, None])

    signals = await clarify_retriever(session, FakeEmbedder()).scope_signals(AreaScope.external, "x")

    assert [(c.kind, c.item_id, c.area_id, c.label) for c in signals.candidates] == [
        ("faq", 12, 2, "¿Cuota?"), ("procedure", 7, 3, "Copia del contrato")]
    assert "(faq.embedding <=> %(embedding_1)s) <= %(param_1)s" in sql(session.statements[0])
    assert not signals.other_scope_match


@pytest.mark.anyio
async def test_scope_signals_sin_umbral_de_aclaracion_no_da_candidates():
    session = ScopeSession([SIGNAL_FAQS, SIGNAL_PROCEDURES], scalars=[None, None])

    signals = await clarify_retriever(session, FakeEmbedder(), clarify=None).scope_signals(AreaScope.external, "x")

    assert signals.candidates == [] and signals.own_area_ids == [1]


@pytest.mark.anyio
async def test_search_area_filtra_por_area_y_reutiliza_el_embedding():
    session = ScopeSession([[FAQ_ROW], [PROCEDURE_ROW], [RUT]])
    embedder = FakeEmbedder()

    knowledge = await clarify_retriever(session, embedder).search_area(1, [0.3] * 768)

    assert embedder.queries == []
    for statement in session.statements[:2]:
        where = sql(statement).split("WHERE", 1)[1]
        assert "area_id = %(area_id_1)s" in where and "business_area.active" in where
    assert [hit.id for hit in knowledge.faqs] == [11]
    assert [(p.id, [f.name for f in p.fields]) for p in knowledge.procedures] == [(7, ["rut"])]


@pytest.mark.anyio
async def test_search_area_faqs_y_area_procedures_calculan_su_embedding():
    faq_session = ScopeSession([[FAQ_ROW]])
    procedure_session = ScopeSession([[PROCEDURE_ROW], [RUT]])
    embedder = FakeEmbedder()

    faqs = await clarify_retriever(faq_session, embedder).search_area_faqs(1, "plazo del crédito")
    procedures = await clarify_retriever(procedure_session, embedder).search_area_procedures(1, "copia")

    assert embedder.queries == ["plazo del crédito", "copia"]
    assert [hit.id for hit in faqs] == [11] and [p.id for p in procedures] == [7]
    assert "area_id = %(area_id_1)s" in sql(faq_session.statements[0])


@pytest.mark.anyio
async def test_get_faq_solo_activa_y_del_area():
    found = ScopeSession([], scalars=[Row(id=11, question="¿Plazo?", answer="48 meses")])
    missing = ScopeSession([], scalars=[None])

    hit = await clarify_retriever(found, FakeEmbedder()).get_faq(1, 11)

    assert hit is not None and (hit.id, hit.area_id, hit.answer) == (11, 1, "48 meses")
    assert await clarify_retriever(missing, FakeEmbedder()).get_faq(1, 99) is None
    where = sql(found.statements[0]).split("WHERE", 1)[1]
    assert "faq.active" in where and "faq_category.area_id" in where
