from collections.abc import Awaitable, Callable
from typing import Annotated
import httpx
from fastapi import Depends
from src.database.session import SessionDep
from src.services.assistant import AssistantDeps, pg_deps
from src.services.google_chat import verify_addon_token
from src.services.property import get_property
from src.utils.exceptions.google_chat import InvalidGoogleTokenError

HTTP_TIMEOUT_SECONDS = 10

TokenVerifier = Callable[[str | None], Awaitable[None]]

def get_assistant_deps(session: SessionDep) -> AssistantDeps:
    return pg_deps(session)

def get_token_verifier(session: SessionDep) -> TokenVerifier:
    async def verify(token: str | None) -> None:
        # Sin token se rechaza antes de leer la configuración: 401 aunque falte configurar el complemento (RF-35).
        if not token:
            raise InvalidGoogleTokenError("Falta el token Bearer")
        # Sin caché: un cambio de audiencia o de cuenta de servicio se aplica desde el siguiente evento (RF-23).
        audience = await get_property(session, "google_chat_audience")
        service_account = await get_property(session, "google_chat_addon_service_account")
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as http:
            await verify_addon_token(token, audience, service_account, http)
    return verify

AssistantDepsDep = Annotated[AssistantDeps, Depends(get_assistant_deps)]
TokenVerifierDep = Annotated[TokenVerifier, Depends(get_token_verifier)]
