from collections.abc import Callable
from functools import lru_cache
from typing import Protocol
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.llm import FaqHit, get_llm_property
from src.models.faq import EMBEDDING_DIMENSIONS, Faq
from src.models.faq_category import FaqCategory
from src.services.property import get_float_property, get_int_property
from src.utils.exceptions.agent import LlmUnavailableError
from src.utils.exceptions.database import DatabaseUnavailableError

SessionFactory = Callable[[], AsyncSession]

class Embedder(Protocol):
    async def embed_query(self, text: str) -> list[float]: ...
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

class Retriever(Protocol):
    async def search(self, area_id: int, question: str) -> list[FaqHit]: ...
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
    def __init__(self, session_factory: SessionFactory, embedder: Embedder, top_k: int, min_similarity: float):
        self._session_factory = session_factory
        self._embedder = embedder
        self._top_k = top_k
        self._min_similarity = min_similarity

    async def search(self, area_id: int, question: str) -> list[FaqHit]:
        embedding = await self._embedder.embed_query(question)
        distance = Faq.embedding.cosine_distance(embedding)
        statement = (
            select(Faq.question, Faq.answer, distance.label("distance"))
            .join(FaqCategory, Faq.category_id == FaqCategory.id)
            .where(FaqCategory.area_id == area_id, Faq.active, distance <= 1 - self._min_similarity)
            .order_by(distance)
            .limit(self._top_k)
        )
        try:
            async with self._session_factory() as session:
                rows = list(await session.execute(statement))
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc
        return [FaqHit(row.question, row.answer, 1 - row.distance) for row in rows]

    async def refresh_stale_embeddings(self, area_ids: list[int]) -> None:
        statement = (
            select(Faq)
            .join(FaqCategory, Faq.category_id == FaqCategory.id)
            .where(FaqCategory.area_id.in_(area_ids), Faq.active, Faq.embedded_hash.is_distinct_from(Faq.content_hash))
        )
        try:
            async with self._session_factory() as session:
                faqs = list((await session.execute(statement)).scalars())
                if not faqs:
                    return
                embeddings = await self._embedder.embed_documents([f"{faq.question}\n{faq.answer}" for faq in faqs])
                for faq, embedding in zip(faqs, embeddings):
                    faq.embedding = embedding
                    faq.embedded_hash = faq.content_hash
                await session.commit()
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc

async def build_faq_retriever(session: AsyncSession, session_factory: SessionFactory) -> FaqRetriever:
    api_key = await get_llm_property(session, "gemini_api_key")
    model = await get_llm_property(session, "gemini_embedding_model")
    return FaqRetriever(
        session_factory,
        GeminiEmbedder(gemini_embeddings(model, api_key)),
        top_k=await get_int_property(session, "rag_top_k", 4),
        # Calibrado con las FAQ de Servicio al Cliente (R3 del plan de la spec 001).
        min_similarity=await get_float_property(session, "rag_min_similarity", 0.68),
    )

# Mismo motivo que gemini_chat: reutilizar las conexiones mientras no cambie la configuración.
@lru_cache(maxsize=4)
def gemini_embeddings(model: str, api_key: str) -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(model=model, api_key=SecretStr(api_key))
