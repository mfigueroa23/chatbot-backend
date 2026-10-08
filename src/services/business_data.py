from dataclasses import dataclass, field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.agent_prompt import AgentPrompt
from src.models.business_area import AreaScope, BusinessArea
from src.models.fallback_space import FallbackSpace
from src.models.faq import Faq
from src.models.faq_category import FaqCategory
from src.models.official_channel import OfficialChannel
from src.models.procedure import Procedure
from src.utils.exceptions.database import DatabaseUnavailableError

# Sin caché a propósito: los cambios de áreas y prompts se aplican desde el siguiente mensaje.

@dataclass(frozen=True)
class AreaTopics:
    """Lo que el agente de ámbito sabe de un área: los nombres de sus FAQ y procedimientos, nunca su contenido."""
    faqs: list[str] = field(default_factory=list)
    procedures: list[str] = field(default_factory=list)

async def get_areas(session: AsyncSession, scope: AreaScope) -> list[BusinessArea]:
    statement = select(BusinessArea).where(BusinessArea.scope == scope, BusinessArea.active).order_by(BusinessArea.id)
    try:
        return list((await session.execute(statement)).scalars())
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc

async def get_agent_prompt(session: AsyncSession, key: str) -> str | None:
    try:
        return await session.scalar(select(AgentPrompt.content).where(AgentPrompt.key == key))
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc

async def get_official_channels(session: AsyncSession) -> list[OfficialChannel]:
    try:
        result = await session.execute(select(OfficialChannel).order_by(OfficialChannel.position, OfficialChannel.id))
        return list(result.scalars())
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc

async def get_fallback_space(session: AsyncSession, scope: AreaScope) -> str | None:
    try:
        return await session.scalar(select(FallbackSpace.chat_space).where(FallbackSpace.scope == scope))
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc

async def get_area_topics(session: AsyncSession, area_ids: list[int], limit: int) -> dict[int, AreaTopics]:
    if not area_ids:
        return {}
    faqs = (select(Faq.question.label("label"), FaqCategory.area_id)
            .join(FaqCategory, Faq.category_id == FaqCategory.id)
            .join(BusinessArea, FaqCategory.area_id == BusinessArea.id)
            .where(FaqCategory.area_id.in_(area_ids), Faq.active, BusinessArea.active)
            .order_by(FaqCategory.area_id, Faq.id))
    procedures = (select(Procedure.name.label("label"), Procedure.area_id)
                  .join(BusinessArea, Procedure.area_id == BusinessArea.id)
                  .where(Procedure.area_id.in_(area_ids), Procedure.active, BusinessArea.active)
                  .order_by(Procedure.area_id, Procedure.id))
    try:
        faq_rows = list(await session.execute(faqs))
        procedure_rows = list(await session.execute(procedures))
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc
    # El tope por área evita que el prompt del agente de ámbito crezca sin control.
    grouped: dict[int, AreaTopics] = {}
    for rows, pick in ((faq_rows, lambda topics: topics.faqs), (procedure_rows, lambda topics: topics.procedures)):
        for row in rows:
            labels = pick(grouped.setdefault(row.area_id, AreaTopics()))
            if len(labels) < limit:
                labels.append(row.label)
    return grouped
