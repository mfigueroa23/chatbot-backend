"""Herramientas del EDR del área Proyectos (spec 003, RF-7, RF-13, RF-15 a RF-18). generar_edr agenda el trabajo en
segundo plano y responde al momento; el enlace llega después al hilo (plan 003, D3)."""
import asyncio
import json
import logging
import uuid
from collections.abc import Callable, Coroutine
from typing import Any
import httpx
from pydantic import BaseModel, Field
from src.agents.gemini import gemini_edr_writer
from src.agents.llm import EdrWriter
from src.agents.prompts import information
from src.agents.tools.registry import AreaTool, ToolContext, code_tool
from src.services.edr.document import EdrDocument, edr_config, pending_sections
from src.services.edr.job import EdrJobDeps, EdrRequest, run_edr_job
from src.services.edr.store import EdrRepository, PgEdrRepository
from src.services.property import Properties
from src.utils.exceptions.edr import EdrNotConfiguredError
from src.utils.exceptions.property import PropertyNotFoundError

logger = logging.getLogger(__name__)

STARTED = ("Se empezó a generar el EDR. El enlace se publicará en esta conversación cuando el documento esté listo, en "
           "unos minutos.")
IN_PROGRESS = "Ya se está generando un EDR en esta conversación; el enlace se publicará aquí cuando esté listo."
ONLY_GOOGLE_CHAT = "El EDR solo se puede generar desde Google Chat."
NOT_CONFIGURED = "No se puede generar el EDR en este momento."
NO_EDR = "Todavía no hay un EDR en esta conversación."

# Conversaciones con un EDR en curso (RF-15) y las tareas vivas: asyncio solo guarda referencias débiles a una tarea.
RUNNING: set[uuid.UUID] = set()
TASKS: set[asyncio.Task[None]] = set()

Scheduler = Callable[[Coroutine[Any, Any, None]], None]
RepositoryFactory = Callable[[ToolContext], EdrRepository]
WriterFactory = Callable[[Properties], EdrWriter]

def pg_repository(context: ToolContext) -> EdrRepository:
    if context.session_factory is None:
        raise EdrNotConfiguredError("no hay fábrica de sesiones")
    return PgEdrRepository(context.session_factory)

def background(job: Coroutine[Any, Any, None]) -> None:
    task = asyncio.create_task(job)
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)

class EdrOrder(BaseModel):
    # Sin valores por defecto: Gemini no los admite en el esquema de una herramienta (plan 003, D5).
    pedido: str = Field(description="Lo que pide la persona para el EDR: el proyecto, los cambios o los datos que entregó")
    clave_epica: str = Field(description="Clave de la épica de Jira, por ejemplo DAIA-250; vacío si no indicó una")
    nuevo: bool = Field(description="true solo si pide otro EDR en vez de cambiar el de esta conversación")

class NoArgs(BaseModel):
    pass

def edr_tools(read_ticket: AreaTool, repository_for: RepositoryFactory = pg_repository,
              writer_for: WriterFactory = gemini_edr_writer, schedule: Scheduler = background,
              transport: httpx.AsyncBaseTransport | None = None) -> list[AreaTool]:
    """read_ticket es leer_ticket de Jira (plan 003, D6); el resto se reemplaza en los tests."""

    async def generate(args: EdrOrder, context: ToolContext) -> str:
        conversation_id, chat_key = context.conversation_id, context.chat_key
        if conversation_id is None or chat_key is None:
            return ONLY_GOOGLE_CHAT
        if conversation_id in RUNNING:
            return IN_PROGRESS
        try:
            # La configuración se revisa antes de agendar: sin ella no se promete un enlace (RF-18).
            config = edr_config(context.properties)
            deps = EdrJobDeps(repository_for(context), writer_for(context.properties),
                              lambda key: read_ticket.run({"clave": key}, context), transport)
        except (EdrNotConfiguredError, PropertyNotFoundError) as exc:
            logger.error("El EDR no está configurado: %s", exc)
            return NOT_CONFIGURED
        request = EdrRequest(conversation_id, chat_key, args.pedido, context.message,
                             args.clave_epica.strip().upper() or None, args.nuevo)

        async def job() -> None:
            try:
                await run_edr_job(request, config, context.properties, deps)
            finally:
                RUNNING.discard(conversation_id)

        RUNNING.add(conversation_id)
        schedule(job())
        return STARTED

    async def read(args: NoArgs, context: ToolContext) -> str:
        if context.conversation_id is None or context.chat_key is None:
            return ONLY_GOOGLE_CHAT
        running = context.conversation_id in RUNNING
        try:
            current = await repository_for(context).latest(context.conversation_id)
        except EdrNotConfiguredError:
            return NOT_CONFIGURED
        if current is None:
            return IN_PROGRESS if running else NO_EDR
        edr = EdrDocument.model_validate(current.content)
        pending = ", ".join(pending_sections(edr)) or "ninguna"
        body = (f"Título: {current.title}\nEnlace: {current.web_link}\nSecciones pendientes: {pending}"
                f"\nEDR: {json.dumps(current.content, ensure_ascii=False)}")
        # El EDR lo redactó el modelo con lo que entregaron las personas: es información (spec 003, RF-20).
        return information("EDR de la conversación", body) + (f"\n{IN_PROGRESS}" if running else "")

    return [
        code_tool("generar_edr", "Genera el EDR de un proyecto como Google Doc, o cambia el de esta conversación, con "
                  "la conversación, los archivos compartidos y la épica de Jira. Corre en segundo plano: el enlace se "
                  "publica después en la conversación.", EdrOrder, generate),
        code_tool("leer_edr", "Lee el EDR de esta conversación: título, enlace, secciones pendientes y contenido.",
                  NoArgs, read),
    ]
