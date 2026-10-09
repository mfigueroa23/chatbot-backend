import logging
from dataclasses import dataclass
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from src.utils.exceptions.database import DatabaseUnavailableError
from src.utils.exceptions.property import PropertyNotFoundError
from src.models.property import Property

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class Properties:
    """Foto de la tabla property al empezar un mensaje: todos sus pasos usan los mismos valores."""
    values: dict[str, str]

    def required(self, key: str) -> str:
        if key not in self.values:
            raise PropertyNotFoundError(key)
        return self.values[key]

    def get_int(self, key: str, default: int) -> int:
        try:
            return int(self.values[key])
        except KeyError:
            return default
        except ValueError:
            logger.warning("La property '%s' no es un entero; se usa %s", key, default)
            return default

# Sin caché: un cambio en la tabla se aplica desde la siguiente lectura (RF-23).
async def get_property(session: AsyncSession, key: str) -> str:
    logger.debug("Leyendo la property %s", key)
    try:
        value = await session.scalar(select(Property.value).where(Property.key == key))
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc
    if value is None:
        raise PropertyNotFoundError(key)
    return value

async def load_properties(session: AsyncSession) -> Properties:
    logger.debug("Leyendo todas las properties")
    try:
        result = await session.execute(select(Property.key, Property.value))
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc
    return Properties({row.key: row.value for row in result})
