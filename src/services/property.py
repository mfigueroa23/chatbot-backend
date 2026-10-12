import logging
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from src.utils.exceptions.database import DatabaseUnavailableError
from src.utils.exceptions.property import PropertyNotFoundError
from src.models.property import Property

logger = logging.getLogger(__name__)

async def get_property(session: AsyncSession, key: str) -> str:
    try:
        logger.debug(f"Obteniendo propiedad '{key}'")
        result = await session.execute(
            select(Property.value).where(Property.key == key)
        )
        value = result.scalar_one_or_none()
        if value is None:
            logger.warning(f"La propiedad '{key}' no se encuenta en la base de datos")
            raise PropertyNotFoundError(key)
        return value
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc
