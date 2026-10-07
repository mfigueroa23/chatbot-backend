from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.agent_prompt import AgentPrompt
from src.models.business_area import AreaScope, BusinessArea
from src.models.fallback_space import FallbackSpace
from src.models.official_channel import OfficialChannel
from src.utils.exceptions.database import DatabaseUnavailableError

# Sin caché a propósito: los cambios de áreas y prompts se aplican desde el siguiente mensaje.

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
