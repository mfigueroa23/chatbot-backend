"""Contenido de las áreas: catálogo del canal, búsqueda de FAQ (pgvector) y embeddings pendientes. Todo se lee sin
caché en cada mensaje, así que un cambio en la BD se aplica desde el siguiente (RF-23)."""
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.llm import AreaInfo, Catalog, Embedder, FaqHit, KnowledgeSource, McpServerConfig, Subtask
from src.models.agent_prompt import AgentPrompt
from src.models.area_member import AreaMember
from src.models.business_area import AreaScope, BusinessArea
from src.models.faq import Faq
from src.models.faq_category import FaqCategory
from src.models.mcp_server import McpServer
from src.utils.exceptions.database import DatabaseUnavailableError

logger = logging.getLogger(__name__)

SUB_AGENT_RULES = "sub_agent_rules"

@dataclass(frozen=True)
class FaqRow:
    id: int
    question: str
    answer: str
    content_hash: str
    embedded_hash: str | None

def build_catalog(areas: Sequence[BusinessArea], categories: Sequence[FaqCategory], prompts: Mapping[str, str],
                  scope: AreaScope, members: Sequence[AreaMember] = (),
                  servers: Sequence[McpServer] = ()) -> Catalog:
    """Solo las áreas activas del canal (RF-3, RF-4), con sus categorías para «qué puedo consultar» (RF-16), sus
    colaboradores habilitados y sus servidores MCP activos (spec 002, RF-4, RF-9)."""
    for key in (f"{scope}_coordinator", SUB_AGENT_RULES):
        if key not in prompts:
            logger.warning("Falta el prompt %s en agent_prompt", key)
    names_by_area: dict[int, list[str]] = {}
    for category in categories:
        names_by_area.setdefault(category.area_id, []).append(category.name)
    emails_by_area: dict[int, set[str]] = {}
    for member in members:
        emails_by_area.setdefault(member.area_id, set()).add(member.email.strip().lower())
    infos = tuple(AreaInfo(area.id, area.name, area.description, area.system_prompt or "",
                           tuple(sorted(names_by_area.get(area.id, []))), tuple(area.tools or ()),
                           frozenset(emails_by_area[area.id]) if area.id in emails_by_area else None,
                           tuple(area.mcp_servers or ()))
                  for area in sorted(areas, key=lambda area: area.id) if area.active and area.scope == scope)
    assigned = {name for info in infos for name in info.mcp_servers}
    configs = {server.name: McpServerConfig(server.name, server.url, server.credential_key,
                                            tuple(server.allowed_tools or ()))
               for server in servers if server.active and server.name in assigned}
    return Catalog(scope, prompts.get(f"{scope}_coordinator", ""), prompts.get(SUB_AGENT_RULES, ""), infos, configs)

async def load_catalog(session: AsyncSession, scope: AreaScope) -> Catalog:
    logger.debug("Cargando el catálogo del canal %s", scope)
    try:
        areas = (await session.scalars(select(BusinessArea))).all()
        categories = (await session.scalars(select(FaqCategory))).all()
        prompts = {row.key: row.content for row in await session.execute(select(AgentPrompt.key, AgentPrompt.content))}
        members = (await session.scalars(select(AreaMember))).all()
        servers = (await session.scalars(select(McpServer))).all()
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc
    return build_catalog(areas, categories, prompts, scope, members, servers)

async def load_prompt(session: AsyncSession, key: str) -> str | None:
    try:
        return await session.scalar(select(AgentPrompt.content).where(AgentPrompt.key == key))
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc

def pending_faqs(rows: Sequence[FaqRow]) -> list[FaqRow]:
    """FAQ nuevas o editadas: su contenido cambió desde el último embedding (RF-24)."""
    return [row for row in rows if row.embedded_hash != row.content_hash]

def embedding_text(row: FaqRow) -> str:
    return f"{row.question}\n{row.answer}"

class PgKnowledge(KnowledgeSource):
    def __init__(self, session: AsyncSession, embedder: Embedder):
        self._session = session
        self._embedder = embedder

    async def search(self, subtasks: Sequence[Subtask], k: int) -> dict[int, list[FaqHit]]:
        area_ids = sorted({subtask.area_id for subtask in subtasks})
        try:
            await self._sync_embeddings(area_ids)
            vectors = await self._embedder.embed([subtask.query for subtask in subtasks])
            # Consultas en serie sobre la sesión del mensaje: AsyncSession no admite consultas concurrentes (D6).
            return {subtask.area_id: await self._nearest(subtask.area_id, vector, k)
                    for subtask, vector in zip(subtasks, vectors, strict=True)}
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc

    async def _sync_embeddings(self, area_ids: list[int]) -> None:
        result = await self._session.execute(
            select(Faq.id, Faq.question, Faq.answer, Faq.content_hash, Faq.embedded_hash)
            .join(FaqCategory, FaqCategory.id == Faq.category_id)
            .where(FaqCategory.area_id.in_(area_ids), Faq.active, Faq.embedded_hash.is_distinct_from(Faq.content_hash)))
        pending = pending_faqs([FaqRow(row.id, row.question, row.answer, row.content_hash, row.embedded_hash)
                                for row in result])
        if not pending:
            return
        logger.info("Generando el embedding de %s FAQ nuevas o editadas", len(pending))
        vectors = await self._embedder.embed([embedding_text(row) for row in pending])
        for row, vector in zip(pending, vectors, strict=True):
            await self._session.execute(update(Faq).where(Faq.id == row.id)
                                        .values(embedding=vector, embedded_hash=row.content_hash))
        await self._session.commit()

    async def _nearest(self, area_id: int, vector: list[float], k: int) -> list[FaqHit]:
        result = await self._session.execute(
            select(Faq.id, FaqCategory.name, Faq.question, Faq.answer)
            .join(FaqCategory, FaqCategory.id == Faq.category_id)
            .where(FaqCategory.area_id == area_id, Faq.active, Faq.embedding.is_not(None))
            .order_by(Faq.embedding.cosine_distance(vector))
            .limit(k))
        return [FaqHit(row.id, row.name, row.question, row.answer) for row in result]
