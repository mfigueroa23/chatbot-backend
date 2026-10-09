"""Un mensaje de punta a punta: validar → properties → conversación → catálogo → grafo → guardar el turno."""
import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from langchain_core.messages import BaseMessage, HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession
from src.database.session import SessionLocal
from src.agents.gemini import GeminiModels, gemini_models
from src.agents.graph import AgentContext, Limits, run_graph
from src.agents.llm import Catalog, CoordinatorModel, Embedder, KnowledgeSource, SubAgentModel, Transcriber
from src.models.business_area import AreaScope
from src.models.conversation import Channel
from src.services.conversation import ConversationStore, PgConversationStore
from src.services.files.attachments import Attachment, AttachmentText, files_block, limits_from
from src.services.google.chat_media import read_chat_attachments
from src.services.knowledge import PgKnowledge, load_catalog, load_prompt
from src.services.message_validation import validate_user_message
from src.services.property import Properties, load_properties
from src.utils.exceptions.llm import LlmUnavailableError
from src.utils.exceptions.message import InvalidMessageError
from src.utils.exceptions.property import PropertyNotFoundError

logger = logging.getLogger(__name__)

UNAVAILABLE = "El asistente no está disponible en este momento. La consulta se puede repetir en unos minutos."
DEFAULT_WELCOME = "¡Hola! Soy el asistente virtual. Pregúntame «¿qué puedo consultar?» para ver los temas."
SCOPES = {Channel.web: AreaScope.external, Channel.google_chat: AreaScope.internal}

@dataclass(frozen=True)
class Models:
    coordinator: CoordinatorModel
    sub_agent: SubAgentModel
    embedder: Embedder
    transcriber: Transcriber | None = None

# Lee los adjuntos de un mensaje (Google Chat en producción, un doble en los tests): spec 002, RF-31.
FileReader = Callable[[Sequence[Attachment], Properties, Transcriber], Awaitable[list[AttachmentText]]]

@dataclass(frozen=True)
class AssistantDeps:
    """Lo que necesita un mensaje; los routers lo arman con la sesión y los tests con dobles."""
    properties: Callable[[], Awaitable[Properties]]
    conversations: ConversationStore
    catalog: Callable[[AreaScope], Awaitable[Catalog]]
    models: Callable[[Properties], Models]
    knowledge: Callable[[Embedder], KnowledgeSource]
    prompt: Callable[[str], Awaitable[str | None]]
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    # Sesiones propias para las herramientas, que corren en paralelo (spec 002, plan D11).
    session_factory: Callable[[], AsyncSession] | None = None
    read_files: FileReader | None = None

@dataclass(frozen=True)
class AssistantReply:
    conversation_id: uuid.UUID
    reply: str

def to_models(models: GeminiModels) -> Models:
    return Models(models.coordinator, models.sub_agent, models.embedder, models.transcriber)

def pg_deps(session: AsyncSession) -> AssistantDeps:
    return AssistantDeps(
        properties=lambda: load_properties(session),
        conversations=PgConversationStore(session),
        catalog=lambda scope: load_catalog(session, scope),
        models=lambda properties: to_models(gemini_models(properties)),
        knowledge=lambda embedder: PgKnowledge(session, embedder, SessionLocal),
        prompt=lambda key: load_prompt(session, key),
        session_factory=SessionLocal,
        read_files=read_chat_attachments)

def limits(properties: Properties) -> Limits:
    return Limits(max_areas=properties.get_int("max_areas_per_message", 3),
                  faqs_per_search=properties.get_int("faqs_per_search", 5),
                  sub_agent_max_steps=properties.get_int("sub_agent_max_steps", 3),
                  sub_agent_timeout=properties.get_int("sub_agent_timeout_seconds", 6))

def trim_history(history: Sequence[BaseMessage]) -> list[BaseMessage]:
    # Empieza en un mensaje del usuario: la ventana no corta un intercambio por la mitad.
    messages = list(history)
    while messages and not isinstance(messages[0], HumanMessage):
        messages.pop(0)
    return messages

async def welcome(deps: AssistantDeps) -> str:
    """Presentación fija al agregar el asistente a un space o DM: sin llamar al modelo (RF-37, D13)."""
    text = await deps.prompt("internal_welcome")
    if not text:
        logger.warning("Falta el prompt internal_welcome en agent_prompt; se usa el texto por defecto")
    return text or DEFAULT_WELCOME

async def read_files(deps: AssistantDeps, attachments: Sequence[Attachment], properties: Properties,
                     models: Models) -> str:
    """Bloque de información con los archivos leídos (spec 002, RF-31 a RF-41); su contenido nunca va al log."""
    started = time.perf_counter()
    if deps.read_files is None or models.transcriber is None:
        texts = [AttachmentText(item.name, "failed") for item in attachments]
    else:
        texts = await deps.read_files(attachments, properties, models.transcriber)
    logger.info("Paso files: %.2f s (%s archivos)", time.perf_counter() - started, len(attachments))
    return files_block(texts, limits_from(properties))

async def answer(deps: AssistantDeps, channel: Channel, conversation: uuid.UUID | str | None,
                 text: str, requester: str | None = None,
                 attachments: Sequence[Attachment] = ()) -> AssistantReply:
    """DatabaseUnavailableError se propaga: el router la traduce a 503 (RF-34)."""
    started = time.perf_counter()
    now = deps.now()
    if isinstance(conversation, str):
        conversation_id = await deps.conversations.chat_conversation(conversation, now)
    else:
        conversation_id = await deps.conversations.web_conversation(conversation, now)
    try:
        question = validate_user_message(text, has_files=bool(attachments))
    except InvalidMessageError as exc:
        return AssistantReply(conversation_id, exc.reply)
    properties = await deps.properties()
    try:
        models = deps.models(properties)
    except PropertyNotFoundError as exc:
        # Solo el nombre de la clave: el valor de la API key nunca se registra (RF-26, RNF-3).
        logger.error("Falta la property %s: el asistente no puede responder", exc.key)
        return AssistantReply(conversation_id, UNAVAILABLE)
    history = trim_history(await deps.conversations.history(conversation_id,
                                                            properties.get_int("history_messages", 10)))
    context = AgentContext(await deps.catalog(SCOPES[channel]), models.coordinator, models.sub_agent,
                           deps.knowledge(models.embedder), limits(properties), requester=requester,
                           properties=properties, session_factory=deps.session_factory)
    # Con archivos el tope es otro: leerlos suma segundos y Google Chat espera hasta 30 s (spec 002, RNF-7; plan D3).
    timeout = (properties.get_int("file_response_timeout_seconds", 27) if attachments
               else properties.get_int("response_timeout_seconds", 20))
    try:
        async with asyncio.timeout(timeout):
            if attachments:
                # El bloque queda en el mensaje del usuario: se guarda en el historial y sirve después (RF-35).
                question = "\n\n".join(part for part in (question, await read_files(deps, attachments, properties, models))
                                       if part)
            reply = (await run_graph(context, history, question)).strip()
    except TimeoutError:
        logger.error("El asistente superó los %s s de respuesta", timeout)
        return AssistantReply(conversation_id, UNAVAILABLE)
    except LlmUnavailableError as exc:
        logger.error("El modelo no está disponible: %s", exc)
        return AssistantReply(conversation_id, UNAVAILABLE)
    if not reply:
        logger.error("El modelo devolvió una respuesta vacía")
        return AssistantReply(conversation_id, UNAVAILABLE)
    await deps.conversations.append_turn(conversation_id, question, reply, deps.now())
    # Sin el texto del mensaje ni de la respuesta (RNF-3); la duración sirve para medir el p95 (RNF-1).
    logger.info("Mensaje del canal %s respondido en %.2f s", channel, time.perf_counter() - started)
    return AssistantReply(conversation_id, reply)
