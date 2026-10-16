import logging
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send
from src.database.session import SessionLocal
from src.services.cors import is_origin_allowed
from src.utils.exceptions.database import DatabaseUnavailableError

logger = logging.getLogger(__name__)

async def origin_allowed(origin: str) -> bool:
    # Falla cerrado: cualquier error al consultar deja el origen como no permitido (decisión D7 del plan 002).
    try:
        async with SessionLocal() as session:
            return await is_origin_allowed(session, origin)
    except DatabaseUnavailableError as exc:
        logger.error("CORS: no se pudo consultar el origen '%s', se trata como no permitido (%s)", origin, exc)
    except Exception:
        logger.exception("CORS: error inesperado al consultar el origen '%s', se trata como no permitido", origin)
    return False

class DatabaseCORSMiddleware:
    """CORS con los orígenes habilitados en la tabla cors_origins, consultada en cada petición con Origin."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        origin = Headers(scope=scope).get("origin")
        # Sin Origin (Google Chat, probes de Kubernetes) no se consulta la tabla ni se emiten cabeceras CORS.
        # Con un origen no permitido la petición se procesa igual y el navegador bloquea la respuesta.
        if origin is None or not await origin_allowed(origin):
            await self.app(scope, receive, send)
            return

        # Origen permitido: las cabeceras CORS se agregan en la tarea T05 del plan 002.
        await self.app(scope, receive, send)
