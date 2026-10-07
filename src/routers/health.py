import logging
from fastapi import APIRouter, Response, status
from src.database.session import SessionDep
from src.interfaces.health import HealthResponse
from src.utils.exceptions.database import DatabaseUnavailableError
from src.utils.exceptions.property import PropertyNotFoundError
from src.services.health import check_database
from src.services.property import get_property

router = APIRouter(tags=["Health Checks"])
logger = logging.getLogger(__name__)

@router.get("/")
def liveness() -> bool:
    return True

@router.get("/health", responses = { 503: { "model": HealthResponse } })
async def health(response: Response, session: SessionDep) -> HealthResponse:
    try:
        logger.debug("Health check iniciado")
        await check_database(session)
        service_name = await get_property(session, "service_name")
        return HealthResponse(servicio=service_name, estado="DISPONIBLE")
    except PropertyNotFoundError as exc:
        logger.warning("Health check: %s", exc)
        return HealthResponse(servicio=None, estado="DISPONIBLE")
    except DatabaseUnavailableError as exc:
        logger.error("Health check falló: base de datos no disponible (%s)", exc)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(servicio="NO DISPONIBLE", estado="NO DISPONIBLE")
    except Exception:
        logger.exception("Health check falló por un error inesperado")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(servicio="NO DISPONIBLE", estado="NO DISPONIBLE")
