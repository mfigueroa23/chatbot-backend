import logging
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from src.utils.exceptions.database import DatabaseUnavailableError
from src.utils.exceptions.agents import AgentNotFoundError
from src.models.agents import Agents

logger = logging.getLogger(__name__)

async def get_prompt(session: AsyncSession, name: str) -> str:
    try:
        logger.debug(f"Obteniendo system prompt del agente '{name}'")
        result = await session.execute(
            select(Agents.prompt).where(Agents.name == name)
        )
        value = result.scalar_one_or_none()
        if value is None:
            logger.warning(f"No se encuentra un agente '{name}' configurado")
            raise AgentNotFoundError(name)
        return value
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc
