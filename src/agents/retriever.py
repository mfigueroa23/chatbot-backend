import logging
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.behavior import Candidate
from src.agents.llm import FaqHit, ProcedureHit, get_llm_property
from src.models.business_area import AreaScope, BusinessArea
from src.models.faq import EMBEDDING_DIMENSIONS, Faq
from src.models.faq_category import FaqCategory
from src.models.procedure import Procedure
from src.models.procedure_field import ProcedureField
from src.services.procedures import FieldSpec
from src.services.property import get_float_property, get_int_property
from src.utils.exceptions.agent import LlmUnavailableError
from src.utils.exceptions.database import DatabaseUnavailableError

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AsyncSession]
# Calibrado en el despliegue con las FAQ reales (D15 del plan de la spec 002).
DEFAULT_CLARIFY_SIMILARITY = 0.55
# Filas por tipo para las señales del ámbito: bastan para 3 opciones aunque haya textos repetidos.
SIGNAL_LIMIT = 10

class Embedder(Protocol):
    async def embed_query(self, text: str) -> list[float]: ...
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

@dataclass(frozen=True)
class Knowledge:
    """Lo recuperado del ámbito para un mensaje. Del otro ámbito solo se sabe si se parece: nunca su contenido."""
    faqs: list[FaqHit]
    procedures: list[ProcedureHit]
    other_scope_match: bool

@dataclass(frozen=True)
class ScopeSignals:
    """Lo que el agente del canal necesita del ámbito sin ver contenido: ids, etiquetas y similitudes."""
    embedding: list[float]  # se reutiliza en la búsqueda de cada área: un solo embedding por mensaje
    own_area_ids: list[int]  # áreas con algo sobre el umbral de respuesta
    candidates: list[Candidate]  # entre el umbral de aclaración y el de respuesta
    other_scope_match: bool

@dataclass(frozen=True)
class AreaKnowledge:
    faqs: list[FaqHit]
    procedures: list[ProcedureHit]

class Retriever(Protocol):
    async def search_scope(self, scope: AreaScope, query: str) -> Knowledge: ...
    async def get_procedure(self, area_id: int, procedure_id: int) -> ProcedureHit | None: ...
    async def refresh_stale_embeddings(self, area_ids: list[int]) -> None: ...

class GeminiEmbedder:
    def __init__(self, embeddings: GoogleGenerativeAIEmbeddings):
        self._embeddings = embeddings

    async def embed_query(self, text: str) -> list[float]:
        try:
            return await self._embeddings.aembed_query(
                text, task_type="RETRIEVAL_QUERY", output_dimensionality=EMBEDDING_DIMENSIONS)
        except Exception as exc:
            raise LlmUnavailableError(str(exc)) from exc

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        try:
            return await self._embeddings.aembed_documents(
                texts, task_type="RETRIEVAL_DOCUMENT", output_dimensionality=EMBEDDING_DIMENSIONS)
        except Exception as exc:
            raise LlmUnavailableError(str(exc)) from exc

class FaqRetriever:
    # Cada búsqueda abre su propia sesión: las áreas se consultan en paralelo y una AsyncSession no admite concurrencia.
    def __init__(self, session_factory: SessionFactory, embedder: Embedder, top_k: int, min_similarity: float,
                 clarify_similarity: float | None = None):
        self._session_factory = session_factory
        self._embedder = embedder
        self._top_k = top_k
        self._min_similarity = min_similarity
        self._clarify_similarity = clarify_similarity

    async def search_scope(self, scope: AreaScope, query: str) -> Knowledge:
        # Un solo embedding por mensaje para FAQ, procedimientos y el otro ámbito.
        embedding = await self._embedder.embed_query(query)
        faq_distance = Faq.embedding.cosine_distance(embedding)
        procedure_distance = Procedure.embedding.cosine_distance(embedding)
        max_distance = 1 - self._min_similarity
        faqs_statement = (
            select(Faq.id, Faq.question, Faq.answer, FaqCategory.area_id, faq_distance.label("distance"))
            .join(FaqCategory, Faq.category_id == FaqCategory.id)
            .join(BusinessArea, FaqCategory.area_id == BusinessArea.id)
            .where(BusinessArea.scope == scope, BusinessArea.active, Faq.active, faq_distance <= max_distance)
            .order_by(faq_distance)
            .limit(self._top_k)
        )
        procedures_statement = (
            select(Procedure.id, Procedure.name, Procedure.steps, Procedure.area_id, procedure_distance.label("distance"))
            .join(BusinessArea, Procedure.area_id == BusinessArea.id)
            .where(BusinessArea.scope == scope, BusinessArea.active, Procedure.active, procedure_distance <= max_distance)
            .order_by(procedure_distance)
            .limit(self._top_k)
        )
        other = AreaScope.internal if scope == AreaScope.external else AreaScope.external
        try:
            async with self._session_factory() as session:
                faq_rows = list(await session.execute(faqs_statement))
                procedure_rows = list(await session.execute(procedures_statement))
                fields = await self._fields_of(session, [row.id for row in procedure_rows])
                other_faq = await session.scalar(
                    select(func.min(faq_distance)).select_from(Faq)
                    .join(FaqCategory, Faq.category_id == FaqCategory.id)
                    .join(BusinessArea, FaqCategory.area_id == BusinessArea.id)
                    .where(BusinessArea.scope == other, BusinessArea.active, Faq.active))
                other_procedure = await session.scalar(
                    select(func.min(procedure_distance)).select_from(Procedure)
                    .join(BusinessArea, Procedure.area_id == BusinessArea.id)
                    .where(BusinessArea.scope == other, BusinessArea.active, Procedure.active))
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc
        distances = [distance for distance in (other_faq, other_procedure) if distance is not None]
        return Knowledge(
            [FaqHit(row.question, row.answer, 1 - row.distance, row.id, row.area_id) for row in faq_rows],
            [ProcedureHit(row.id, row.name, row.steps, fields.get(row.id, []), 1 - row.distance, row.area_id)
             for row in procedure_rows],
            bool(distances) and min(distances) <= max_distance,
        )

    async def scope_signals(self, scope: AreaScope, query: str) -> ScopeSignals:
        embedding = await self._embedder.embed_query(query)
        faq_distance = Faq.embedding.cosine_distance(embedding)
        procedure_distance = Procedure.embedding.cosine_distance(embedding)
        answer_distance = 1 - self._min_similarity
        # Sin umbral de aclaración válido solo interesa lo que supera el de respuesta: no hay candidatos.
        signal_distance = 1 - (self._clarify_similarity if self._clarify_similarity is not None else self._min_similarity)
        faqs_statement = (
            select(Faq.id, Faq.question.label("label"), FaqCategory.area_id, faq_distance.label("distance"))
            .join(FaqCategory, Faq.category_id == FaqCategory.id)
            .join(BusinessArea, FaqCategory.area_id == BusinessArea.id)
            .where(BusinessArea.scope == scope, BusinessArea.active, Faq.active, faq_distance <= signal_distance)
            .order_by(faq_distance)
            .limit(SIGNAL_LIMIT)
        )
        procedures_statement = (
            select(Procedure.id, Procedure.name.label("label"), Procedure.area_id, procedure_distance.label("distance"))
            .join(BusinessArea, Procedure.area_id == BusinessArea.id)
            .where(BusinessArea.scope == scope, BusinessArea.active, Procedure.active, procedure_distance <= signal_distance)
            .order_by(procedure_distance)
            .limit(SIGNAL_LIMIT)
        )
        try:
            async with self._session_factory() as session:
                faq_rows = list(await session.execute(faqs_statement))
                procedure_rows = list(await session.execute(procedures_statement))
                other_scope_match = await self._other_scope_match(session, scope, embedding)
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc
        between = lambda row: answer_distance < row.distance <= signal_distance
        own = [row.area_id for row in faq_rows + procedure_rows if row.distance <= answer_distance]
        candidates = [Candidate("faq", row.id, row.area_id, row.label, 1 - row.distance) for row in faq_rows if between(row)]
        candidates += [Candidate("procedure", row.id, row.area_id, row.label, 1 - row.distance)
                       for row in procedure_rows if between(row)]
        return ScopeSignals(embedding, list(dict.fromkeys(own)), candidates, other_scope_match)

    async def _other_scope_match(self, session: AsyncSession, scope: AreaScope, embedding: list[float]) -> bool:
        faq_distance = Faq.embedding.cosine_distance(embedding)
        procedure_distance = Procedure.embedding.cosine_distance(embedding)
        other = AreaScope.internal if scope == AreaScope.external else AreaScope.external
        other_faq = await session.scalar(
            select(func.min(faq_distance)).select_from(Faq)
            .join(FaqCategory, Faq.category_id == FaqCategory.id)
            .join(BusinessArea, FaqCategory.area_id == BusinessArea.id)
            .where(BusinessArea.scope == other, BusinessArea.active, Faq.active))
        other_procedure = await session.scalar(
            select(func.min(procedure_distance)).select_from(Procedure)
            .join(BusinessArea, Procedure.area_id == BusinessArea.id)
            .where(BusinessArea.scope == other, BusinessArea.active, Procedure.active))
        distances = [distance for distance in (other_faq, other_procedure) if distance is not None]
        return bool(distances) and min(distances) <= 1 - self._min_similarity

    async def search_area(self, area_id: int, embedding: list[float]) -> AreaKnowledge:
        try:
            async with self._session_factory() as session:
                faqs = await self._area_faqs(session, area_id, embedding)
                procedures = await self._area_procedures(session, area_id, embedding)
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc
        return AreaKnowledge(faqs, procedures)

    async def search_area_faqs(self, area_id: int, query: str) -> list[FaqHit]:
        # Búsqueda de una tool: el agente del área reformula la consulta, así que necesita su propio embedding.
        embedding = await self._embedder.embed_query(query)
        try:
            async with self._session_factory() as session:
                return await self._area_faqs(session, area_id, embedding)
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc

    async def search_area_procedures(self, area_id: int, query: str) -> list[ProcedureHit]:
        embedding = await self._embedder.embed_query(query)
        try:
            async with self._session_factory() as session:
                return await self._area_procedures(session, area_id, embedding)
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc

    async def _area_faqs(self, session: AsyncSession, area_id: int, embedding: list[float]) -> list[FaqHit]:
        distance = Faq.embedding.cosine_distance(embedding)
        rows = await session.execute(
            select(Faq.id, Faq.question, Faq.answer, FaqCategory.area_id, distance.label("distance"))
            .join(FaqCategory, Faq.category_id == FaqCategory.id)
            .join(BusinessArea, FaqCategory.area_id == BusinessArea.id)
            .where(FaqCategory.area_id == area_id, BusinessArea.active, Faq.active, distance <= 1 - self._min_similarity)
            .order_by(distance)
            .limit(self._top_k)
        )
        return [FaqHit(row.question, row.answer, 1 - row.distance, row.id, row.area_id) for row in rows]

    async def _area_procedures(self, session: AsyncSession, area_id: int, embedding: list[float]) -> list[ProcedureHit]:
        distance = Procedure.embedding.cosine_distance(embedding)
        rows = list(await session.execute(
            select(Procedure.id, Procedure.name, Procedure.steps, Procedure.area_id, distance.label("distance"))
            .join(BusinessArea, Procedure.area_id == BusinessArea.id)
            .where(Procedure.area_id == area_id, BusinessArea.active, Procedure.active, distance <= 1 - self._min_similarity)
            .order_by(distance)
            .limit(self._top_k)
        ))
        fields = await self._fields_of(session, [row.id for row in rows])
        return [ProcedureHit(row.id, row.name, row.steps, fields.get(row.id, []), 1 - row.distance, row.area_id)
                for row in rows]

    async def get_faq(self, area_id: int, faq_id: int) -> FaqHit | None:
        # Solo FAQ activas de un área activa: una opción elegida puede haberse desactivado entre turnos.
        try:
            async with self._session_factory() as session:
                faq = await session.scalar(
                    select(Faq).join(FaqCategory, Faq.category_id == FaqCategory.id)
                    .join(BusinessArea, FaqCategory.area_id == BusinessArea.id)
                    .where(Faq.id == faq_id, FaqCategory.area_id == area_id, Faq.active, BusinessArea.active))
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc
        return FaqHit(faq.question, faq.answer, 1.0, faq.id, area_id) if faq is not None else None

    async def get_procedure(self, area_id: int, procedure_id: int) -> ProcedureHit | None:
        # Solo procedimientos activos del área indicada: un procedimiento en curso no puede cambiar de área.
        try:
            async with self._session_factory() as session:
                procedure = await session.scalar(select(Procedure).where(
                    Procedure.id == procedure_id, Procedure.area_id == area_id, Procedure.active))
                if procedure is None:
                    return None
                fields = await self._fields_of(session, [procedure.id])
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc
        return ProcedureHit(procedure.id, procedure.name, procedure.steps, fields.get(procedure.id, []), 1.0, area_id)

    async def _fields_of(self, session: AsyncSession, procedure_ids: list[int]) -> dict[int, list[FieldSpec]]:
        if not procedure_ids:
            return {}
        rows = (await session.execute(
            select(ProcedureField).where(ProcedureField.procedure_id.in_(procedure_ids))
            .order_by(ProcedureField.procedure_id, ProcedureField.position, ProcedureField.id)
        )).scalars()
        fields: dict[int, list[FieldSpec]] = {}
        for row in rows:
            fields.setdefault(row.procedure_id, []).append(FieldSpec(row.name, row.label, row.kind))
        return fields

    async def refresh_stale_embeddings(self, area_ids: list[int]) -> None:
        stale_faqs = (
            select(Faq)
            .join(FaqCategory, Faq.category_id == FaqCategory.id)
            .where(FaqCategory.area_id.in_(area_ids), Faq.active, Faq.embedded_hash.is_distinct_from(Faq.content_hash))
        )
        stale_procedures = select(Procedure).where(
            Procedure.area_id.in_(area_ids), Procedure.active, Procedure.embedded_hash.is_distinct_from(Procedure.content_hash))
        try:
            async with self._session_factory() as session:
                faqs = list((await session.execute(stale_faqs)).scalars())
                procedures = list((await session.execute(stale_procedures)).scalars())
                items = [(faq, f"{faq.question}\n{faq.answer}") for faq in faqs]
                items += [(procedure, f"{procedure.name}\n{procedure.steps}") for procedure in procedures]
                if not items:
                    return
                embeddings = await self._embedder.embed_documents([text for _, text in items])
                for (item, _), embedding in zip(items, embeddings):
                    item.embedding = embedding
                    item.embedded_hash = item.content_hash
                await session.commit()
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc

async def read_clarify_similarity(session: AsyncSession, min_similarity: float) -> float | None:
    try:
        value = await get_float_property(session, "rag_clarify_similarity", DEFAULT_CLARIFY_SIMILARITY)
    except ValueError:
        logger.warning("La property rag_clarify_similarity no es un número: no se ofrecerán aclaraciones con opciones")
        return None
    if value >= min_similarity:
        logger.warning("La property rag_clarify_similarity (%s) no es menor que rag_min_similarity (%s): "
                       "no se ofrecerán aclaraciones con opciones", value, min_similarity)
        return None
    return value

async def build_faq_retriever(session: AsyncSession, session_factory: SessionFactory) -> FaqRetriever:
    api_key = await get_llm_property(session, "gemini_api_key")
    model = await get_llm_property(session, "gemini_embedding_model")
    # Calibrado con las FAQ de Servicio al Cliente (R3 del plan de la spec 001).
    min_similarity = await get_float_property(session, "rag_min_similarity", 0.68)
    return FaqRetriever(
        session_factory,
        GeminiEmbedder(gemini_embeddings(model, api_key)),
        top_k=await get_int_property(session, "rag_top_k", 4),
        min_similarity=min_similarity,
        clarify_similarity=await read_clarify_similarity(session, min_similarity),
    )

# Mismo motivo que gemini_chat: reutilizar las conexiones mientras no cambie la configuración.
@lru_cache(maxsize=4)
def gemini_embeddings(model: str, api_key: str) -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(model=model, api_key=SecretStr(api_key))
