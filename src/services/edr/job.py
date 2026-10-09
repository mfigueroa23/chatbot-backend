"""Trabajo en segundo plano que redacta el EDR, lo guarda como Google Doc y publica el enlace en el hilo (spec 003,
RF-8 a RF-14; plan D3, D4). Los logs solo llevan pasos y duraciones: nunca el contenido, el nombre ni el enlace."""
import asyncio
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import ValidationError
import httpx
from src.agents.llm import EdrWriter
from src.agents.prompts import edr_correction, edr_messages
from src.services.edr.document import EdrConfig, EdrDocument, pending_sections, render_edr_html
from src.services.edr.store import EdrRecord, EdrRepository
from src.services.google.chat_messages import ChatMessenger
from src.services.google.drive import DriveClient
from src.services.property import Properties
from src.utils.exceptions.edr import InvalidEdrError

logger = logging.getLogger(__name__)

EDR_WRITER_PROMPT = "edr_writer"
EDR_FAILED = ("No pude generar o guardar el EDR esta vez, así que no quedó guardado. Puedes pedírmelo de nuevo en unos "
              "minutos.")
HTTP_TIMEOUT_SECONDS = 30

@dataclass(frozen=True)
class EdrRequest:
    conversation_id: uuid.UUID
    chat_key: str
    request: str
    # El mensaje que pidió el EDR, con sus archivos leídos: todavía no está en el historial (plan 003, D4).
    message: str
    epic_key: str | None
    new: bool

@dataclass(frozen=True)
class EdrJobDeps:
    repository: EdrRepository
    writer: EdrWriter
    # Lee la épica con la herramienta leer_ticket: tableros permitidos y bloque de información (plan 003, D6).
    read_epic: Callable[[str], Awaitable[str]]
    transport: httpx.AsyncBaseTransport | None = None
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

def parse_edr(text: str) -> EdrDocument:
    # Algunos modelos envuelven el JSON en un bloque de código aunque se les pida solo el JSON.
    body = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return EdrDocument.model_validate(json.loads(body))

async def write_edr(writer: EdrWriter, messages: list[BaseMessage]) -> EdrDocument:
    """Como máximo 2 llamadas: la redacción y una corrección con el error de validación (RNF-5)."""
    text = await writer.write(messages)
    try:
        return parse_edr(text)
    except (ValueError, ValidationError) as exc:
        logger.warning("El EDR del modelo no es válido (%s); se pide una corrección", type(exc).__name__)
        retry = [*messages, AIMessage(text), edr_correction(str(exc))]
    text = await writer.write(retry)
    try:
        return parse_edr(text)
    except (ValueError, ValidationError) as exc:
        raise InvalidEdrError(type(exc).__name__) from exc

def with_current_message(history: list[BaseMessage], message: str) -> list[BaseMessage]:
    if not message or (history and isinstance(history[-1], HumanMessage) and history[-1].content == message):
        return history
    return [*history, HumanMessage(message)]

def saved_message(edr: EdrDocument, link: str, created: bool) -> str:
    pending = pending_sections(edr)
    action = "Listo, quedó el EDR" if created else "Listo, actualicé el EDR"
    note = f" Quedaron pendientes: {', '.join(pending)}." if pending else ""
    return f"{action} «{edr.titulo}» en Google Docs: {link}{note}"

async def generate(request: EdrRequest, config: EdrConfig, properties: Properties, deps: EdrJobDeps) -> str:
    repository = deps.repository
    history = await repository.history(request.conversation_id, properties.get_int("edr_history_messages", 30))
    current = None if request.new else await repository.latest(request.conversation_id)
    epic = await deps.read_epic(request.epic_key) if request.epic_key else None
    prompt = await repository.prompt(EDR_WRITER_PROMPT)
    if not prompt:
        logger.warning("Falta el prompt %s en agent_prompt", EDR_WRITER_PROMPT)
    messages = edr_messages(prompt or "", with_current_message(history, request.message),
                            json.dumps(current.content, ensure_ascii=False) if current else None, epic, request.request)
    started = time.perf_counter()
    edr = await write_edr(deps.writer, messages)
    logger.info("Paso edr redacción: %.2f s", time.perf_counter() - started)
    html = render_edr_html(edr, config.template)
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS, transport=deps.transport) as http:
        drive = DriveClient(http, config.service_account)
        upload = (await drive.replace_document_html(current.drive_file_id, html) if current
                  else await drive.create_document_from_html(edr.titulo, config.folder_id, html))
    logger.info("Paso edr drive: %.2f s", time.perf_counter() - started)
    # Si Drive falla no se llega aquí: no queda fila de un EDR que no se guardó (RF-14).
    await repository.save(request.conversation_id,
                          EdrRecord(upload.id, upload.web_link, edr.titulo, edr.model_dump(mode="json")))
    return saved_message(edr, upload.web_link, created=current is None)

async def publish(request: EdrRequest, config: EdrConfig, deps: EdrJobDeps, text: str) -> None:
    """Primero el historial: si la API de Chat falla, el enlace igual queda en la conversación para leer_edr."""
    try:
        await deps.repository.append_reply(request.conversation_id, text, deps.now())
    except Exception as exc:
        logger.error("No se pudo guardar en el historial el resultado del EDR: %s", type(exc).__name__)
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS, transport=deps.transport) as http:
            await ChatMessenger(http, config.service_account).post(request.chat_key, text)
    except Exception as exc:
        logger.error("No se pudo publicar el resultado del EDR en Google Chat: %s", type(exc).__name__)

async def run_edr_job(request: EdrRequest, config: EdrConfig, properties: Properties, deps: EdrJobDeps) -> None:
    timeout = properties.get_int("edr_job_timeout_seconds", 180)
    started = time.perf_counter()
    try:
        async with asyncio.timeout(timeout):
            text = await generate(request, config, properties, deps)
    except TimeoutError:
        logger.error("El EDR superó los %s s", timeout)
        text = EDR_FAILED
    except Exception as exc:
        # Sin detalles al colaborador ni al log: el tipo basta para diagnosticar (RF-14, RNF-2).
        logger.error("No se pudo generar el EDR: %s", type(exc).__name__)
        text = EDR_FAILED
    await publish(request, config, deps, text)
    logger.info("EDR terminado en %.2f s", time.perf_counter() - started)
