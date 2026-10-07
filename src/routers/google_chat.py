import asyncio
import logging
from typing import Annotated, Any
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.database.session import SessionFactoryDep
from src.interfaces.google_chat import AddonEvent, chat_reply
from src.routers.executive import bearer_scheme
from src.services.chat_api_client import build_chat_api_client
from src.services.google_chat import handle_event, verify_addon_token
from src.services.property import get_float_property, get_str_property
from src.utils.exceptions.database import DatabaseUnavailableError
from src.utils.exceptions.google_chat import InvalidGoogleTokenError

router = APIRouter(tags=["Google Chat"])
logger = logging.getLogger(__name__)

PROCESSING = "Estoy procesando tu consulta… te responderé en este hilo en cuanto tenga la respuesta."
HTTP_TIMEOUT_SECONDS = 10

@router.post("/api/v1/google-chat/events")
async def google_chat_events(
    event: AddonEvent,
    request: Request,
    session_factory: SessionFactoryDep,
    # Mismo esquema Bearer JWT que los ejecutivos, pero el token es un ID token de Google para el complemento.
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> dict[str, Any]:
    logger.debug("Evento de Google Chat recibido")
    try:
        async with session_factory() as session, httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as http:
            audience = await get_str_property(session, "google_chat_audience")
            service_account = await get_str_property(session, "google_chat_addon_service_account")
            timeout = await get_float_property(session, "google_chat_sync_timeout_seconds", 25)
            await verify_addon_token(credentials.credentials if credentials else None, audience, service_account, http)
    except InvalidGoogleTokenError as exc:
        logger.warning("Petición de Google Chat rechazada: %s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token de Google Chat no válido") from exc
    except DatabaseUnavailableError as exc:
        logger.error("Google Chat: base de datos no disponible (%s)", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Servicio no disponible") from exc

    async def process() -> str | None:
        async with session_factory() as session:
            return await handle_event(event, session, request.app.state.internal_graph)

    task = asyncio.create_task(process())
    try:
        # shield: si se agota el plazo de Google Chat (30 s) la respuesta se sigue generando y se publica después.
        return chat_reply(await asyncio.wait_for(asyncio.shield(task), timeout))
    except TimeoutError:
        logger.info("La respuesta tarda más de %s s; se publicará en el hilo cuando esté lista", timeout)
        publication = asyncio.create_task(publish_when_ready(task, event, session_factory))
        # Se guarda una referencia para que el recolector de basura no cancele la tarea.
        request.app.state.chat_tasks.add(publication)
        publication.add_done_callback(request.app.state.chat_tasks.discard)
        return chat_reply(PROCESSING)

async def publish_when_ready(task: asyncio.Task[str | None], event: AddonEvent, session_factory: async_sessionmaker[AsyncSession]) -> None:
    try:
        text = await task
        payload = event.chat.message_payload if event.chat else None
        if not text or payload is None or payload.space is None or payload.message is None or payload.message.thread is None:
            return
        async with session_factory() as session, httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as http:
            client = await build_chat_api_client(session, http)
            await client.create_message(payload.space.name, text, thread=payload.message.thread.name)
    except Exception:
        logger.exception("No se pudo publicar en Google Chat la respuesta diferida")
