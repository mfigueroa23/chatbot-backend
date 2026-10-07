import asyncio
import logging
from typing import Annotated
import httpx
from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.database.session import SessionFactoryDep
from src.interfaces.google_chat import ChatEvent
from src.services.google_chat import build_chat_api_client, handle_event, verify_chat_token
from src.services.property import get_float_property, get_str_property
from src.utils.exceptions.database import DatabaseUnavailableError
from src.utils.exceptions.google_chat import InvalidGoogleTokenError

router = APIRouter(tags=["Google Chat"])
logger = logging.getLogger(__name__)

PROCESSING = "Estoy procesando tu consulta… te responderé en este hilo en cuanto tenga la respuesta."
HTTP_TIMEOUT_SECONDS = 10

@router.post("/api/v1/google-chat/events")
async def google_chat_events(
    event: ChatEvent,
    request: Request,
    session_factory: SessionFactoryDep,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    logger.debug("Evento de Google Chat recibido: %s", event.type)
    try:
        async with session_factory() as session, httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as http:
            audience = await get_str_property(session, "google_chat_audience")
            timeout = await get_float_property(session, "google_chat_sync_timeout_seconds", 25)
            await verify_chat_token(authorization, audience, http)
    except InvalidGoogleTokenError as exc:
        logger.warning("Petición de Google Chat rechazada: %s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token de Google Chat no válido") from exc
    except DatabaseUnavailableError as exc:
        logger.error("Google Chat: base de datos no disponible (%s)", exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Servicio no disponible") from exc

    async def process() -> dict[str, str]:
        async with session_factory() as session:
            return await handle_event(event, session)

    task = asyncio.create_task(process())
    try:
        # shield: si se agota el plazo de Google Chat (30 s) la respuesta se sigue generando y se publica después.
        return await asyncio.wait_for(asyncio.shield(task), timeout)
    except TimeoutError:
        logger.info("La respuesta tarda más de %s s; se publicará en el hilo cuando esté lista", timeout)
        publication = asyncio.create_task(publish_when_ready(task, event, session_factory))
        # Se guarda una referencia para que el recolector de basura no cancele la tarea.
        request.app.state.chat_tasks.add(publication)
        publication.add_done_callback(request.app.state.chat_tasks.discard)
        return {"text": PROCESSING}

async def publish_when_ready(task: asyncio.Task[dict[str, str]], event: ChatEvent, session_factory: async_sessionmaker[AsyncSession]) -> None:
    try:
        response = await task
        if "text" not in response or event.space is None or event.message is None or event.message.thread is None:
            return
        async with session_factory() as session, httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as http:
            client = await build_chat_api_client(session, http)
            await client.create_message(event.space.name, event.message.thread.name, response["text"])
    except Exception:
        logger.exception("No se pudo publicar en Google Chat la respuesta diferida")
