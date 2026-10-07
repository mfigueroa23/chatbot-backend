import logging
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from src.utils.exceptions.database import DatabaseUnavailableError
from src.utils.exceptions.property import PropertyNotFoundError
from src.models.property import Property

logger = logging.getLogger(__name__)

async def get_property(session: AsyncSession, key: str) -> str:
    logger.debug("Leyendo la property %s", key)
    try:
        value = await session.scalar(select(Property.value).where(Property.key == key))
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc
    if value is None:
        raise PropertyNotFoundError(key)
    return value

async def get_str_property(session: AsyncSession, key: str, default: str | None = None) -> str:
    try:
        return await get_property(session, key)
    except PropertyNotFoundError:
        if default is None:
            raise
        return default

async def get_int_property(session: AsyncSession, key: str, default: int | None = None) -> int:
    try:
        return int(await get_property(session, key))
    except PropertyNotFoundError:
        if default is None:
            raise
        return default

async def get_float_property(session: AsyncSession, key: str, default: float | None = None) -> float:
    try:
        return float(await get_property(session, key))
    except PropertyNotFoundError:
        if default is None:
            raise
        return default
