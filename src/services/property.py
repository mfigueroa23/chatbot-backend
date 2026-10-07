import logging
import time
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from src.utils.exceptions.database import DatabaseUnavailableError
from src.utils.exceptions.property import PropertyNotFoundError
from src.models.property import Property

logger = logging.getLogger(__name__)
CACHE_TTL_SECONDS = 60

_cache: dict[str, str] = {}
_loaded_at: float | None = None

async def get_property(session: AsyncSession, key: str) -> str:
    global _cache, _loaded_at
    if _loaded_at is None or time.monotonic() - _loaded_at > CACHE_TTL_SECONDS:
        logger.debug("Recargando properties desde la base de datos")
        try:
            result = await session.execute(select(Property.key, Property.value))
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc
        _cache = {row.key: row.value for row in result}
        _loaded_at = time.monotonic()
    if key not in _cache:
        raise PropertyNotFoundError(key)
    return _cache[key]

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
