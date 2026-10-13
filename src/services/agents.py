import logging
from dataclasses import dataclass
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from src.utils.exceptions.database import DatabaseUnavailableError
from src.utils.exceptions.agents import AgentNotFoundError
from src.models.agents import Agents
from src.models.areas import Area

logger = logging.getLogger(__name__)

@dataclass
class SubAgentConfig:
    name: str
    prompt: str
    area: str
    description: str

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

async def list_sub_agents(session: AsyncSession, audiencia: str) -> list[SubAgentConfig]:
    try:
        logger.debug(f"Obteniendo sub-agentes de la audiencia '{audiencia}'")
        result = await session.execute(
            select(Agents.name, Agents.prompt, Area.name, Area.description)
            .join(Area, Area.id == Agents.area_id)
            .where(Area.audiencia == audiencia)
            .order_by(Area.name)
        )
        return [SubAgentConfig(*row) for row in result.all()]
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc
