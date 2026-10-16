import logging
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.cors_origins import CorsOrigin
from src.utils.exceptions.database import DatabaseUnavailableError

logger = logging.getLogger(__name__)

async def is_origin_allowed(session: AsyncSession, origin: str) -> bool:
    # Comparación exacta del texto que envía el navegador, sin normalizar (decisión D5 del plan 002).
    try:
        logger.debug(f"Consultando origen CORS '{origin}'")
        result = await session.execute(
            select(CorsOrigin.id).where(CorsOrigin.origin == origin, CorsOrigin.enabled.is_(True))
        )
        return result.scalar_one_or_none() is not None
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc
