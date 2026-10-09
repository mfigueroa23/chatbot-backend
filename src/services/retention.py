"""Borra las conversaciones sin mensajes desde hace conversation_retention_days días (RF-21, plan D15)."""
import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.services.conversation import PgConversationStore
from src.services.property import load_properties
from src.utils.exceptions.database import DatabaseUnavailableError

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 3600
DEFAULT_RETENTION_DAYS = 30

def retention_cutoff(now: datetime, days: int) -> datetime:
    return now - timedelta(days=days)

async def purge_expired(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        # Sin caché: un cambio de los días de retención se aplica en la siguiente pasada (RF-23).
        days = (await load_properties(session)).get_int("conversation_retention_days", DEFAULT_RETENTION_DAYS)
        return await PgConversationStore(session).delete_expired(retention_cutoff(datetime.now(UTC), days))

async def run_retention(purge: Callable[[], Awaitable[int]], interval: float = INTERVAL_SECONDS) -> None:
    # Espera antes de la primera pasada: arrancar la app no toca la BD. Con varias réplicas el DELETE es idempotente.
    while True:
        await asyncio.sleep(interval)
        try:
            await purge()
        except DatabaseUnavailableError as exc:
            logger.error("Retención: base de datos no disponible (%s)", exc)
        except Exception:
            logger.exception("Retención: error inesperado al borrar conversaciones vencidas")
