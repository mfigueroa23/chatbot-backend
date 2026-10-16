import logging
from starlette.datastructures import Headers
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from src.database.session import SessionLocal
from src.services.cors import is_origin_allowed
from src.utils.exceptions.database import DatabaseUnavailableError

logger = logging.getLogger(__name__)

ORIGEN_NO_PERMITIDO = "Origen no permitido"

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

        headers = Headers(scope=scope)
        origin = headers.get("origin")
        # Sin Origin (Google Chat, probes de Kubernetes) no se consulta la tabla ni se emiten cabeceras CORS.
        if origin is None:
            await self.app(scope, receive, send)
            return

        if not await origin_allowed(origin):
            if scope["method"] == "OPTIONS" and "access-control-request-method" in headers:
                # Preflight rechazado aquí y no en Starlette, que lo responde con cabeceras CORS y en inglés.
                response = PlainTextResponse(ORIGEN_NO_PERMITIDO, status_code=400)
                await response(scope, receive, send)
                return
            # Con un origen no permitido la petición se procesa igual y el navegador bloquea la respuesta.
            await self.app(scope, receive, send)
            return

        # Starlette arma las cabeceras (preflight, Vary, eco de cabeceras) solo para este origen; sin credenciales
        # nunca emite Access-Control-Allow-Credentials y con un origen explícito nunca responde "*".
        cors = CORSMiddleware(
            self.app,
            allow_origins = [origin],
            allow_methods = ["*"],
            allow_headers = ["*"],
            allow_credentials = False,
        )
        await cors(scope, receive, send)
