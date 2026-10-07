import logging
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.graph import AgentContext, AgentGraph, Catalog, build_graph, load_catalog, run_agent
from src.agents.llm import build_gemini_llm
from src.agents.retriever import build_faq_retriever
from src.agents.strategies import ExternalStrategy, InternalStrategy, NoAnswerContext
from src.database.session import SessionLocal, commit
from src.interfaces.web_chat import (
    Channel, ErrorMessage, OfferHuman, OfficialChannels, Queued, RequestContact, ServerMessage, TextMessage)
from src.models.business_area import AreaScope
from src.models.web_session import WebPhase, WebSession
from src.services.business_data import get_official_channels
from src.services.live_chat import enqueue
from src.services.area_notifier import AreaNotifier
from src.services.message_validation import MAX_MESSAGE_LENGTH, validate_user_message
from src.services.web_session import answer_offer, reset_to_bot, start_offer, submit_contact, touch_last_message
from src.utils.clock import Clock
from src.utils.exceptions.agent import LlmNotConfiguredError, LlmUnavailableError
from src.utils.exceptions.database import DatabaseUnavailableError
from src.utils.exceptions.message import EmptyMessageError, MessageTooLongError

logger = logging.getLogger(__name__)

EMPTY_MESSAGE = "Por favor, escribe tu consulta."
TOO_LONG_MESSAGE = f"Tu mensaje supera el máximo de {MAX_MESSAGE_LENGTH} caracteres. Por favor, acórtalo."
UNAVAILABLE = "El servicio no está disponible en este momento. Por favor, intenta más tarde."
MIXED_SCOPE = "Tu pregunta mezcla temas de distintas áreas. Por favor, reformúlala para poder ayudarte."
WAITING_EXECUTIVE = "Tu chat está en espera. Un ejecutivo te atenderá en cuanto esté disponible."
OFFER_REJECTED = "De acuerdo. Puedes reformular tu consulta o contactarnos por nuestros canales oficiales."
CONTACT_EXHAUSTED = "No pudimos validar tus datos de contacto. Puedes contactarnos por nuestros canales oficiales."
HUMAN_REQUESTED = "El cliente pidió hablar con un ejecutivo."

# El canal interno no tiene memoria: su grafo no lleva checkpointer.
internal_graph = build_graph(AreaScope.internal)

async def build_agent_context(session: AsyncSession) -> AgentContext:
    return AgentContext(
        llm=await build_gemini_llm(session),
        retriever=await build_faq_retriever(session, SessionLocal),
        load_catalog=load_catalog_in_own_session,
    )

async def load_catalog_in_own_session(scope: AreaScope) -> Catalog:
    # Sesión propia y breve: la de la petición ya liberó su conexión antes de llamar al modelo.
    async with SessionLocal() as session:
        return await load_catalog(session, scope)

async def release_connection(session: AsyncSession) -> None:
    # Cierra la transacción para devolver la conexión al pool mientras se espera al modelo (varios segundos):
    # retenerla con 50 sesiones a la vez agota el pool de la BD. La sesión sigue usable después.
    await commit(session)

async def handle_internal_message(session: AsyncSession, text: str, user_name: str | None, user_email: str | None) -> str:
    try:
        question = validate_user_message(text)
    except EmptyMessageError:
        return EMPTY_MESSAGE
    except MessageTooLongError:
        return TOO_LONG_MESSAGE
    try:
        context = await build_agent_context(session)
        await release_connection(session)
        result = await run_agent(internal_graph, question, context)
        if result.outcome == "mixed_scope":
            return MIXED_SCOPE
        if result.reply is not None:
            return result.reply
        strategy = InternalStrategy(session, AreaNotifier(SessionLocal))
        reply = await strategy.on_no_answer(NoAnswerContext(question, result.areas, user_name, user_email))
        return reply.text
    except LlmNotConfiguredError:
        return UNAVAILABLE
    except LlmUnavailableError as exc:
        logger.error("El proveedor del LLM no respondió: %s", exc)
        return UNAVAILABLE
    except DatabaseUnavailableError as exc:
        logger.error("Base de datos no disponible al responder en Google Chat: %s", exc)
        return UNAVAILABLE

async def handle_web_message(
    session: AsyncSession, graph: AgentGraph, web_session: WebSession, text: str, clock: Clock
) -> list[ServerMessage]:
    try:
        question = validate_user_message(text)
    except EmptyMessageError:
        return [ErrorMessage(code="empty_message", text=EMPTY_MESSAGE)]
    except MessageTooLongError:
        return [ErrorMessage(code="message_too_long", text=TOO_LONG_MESSAGE)]
    if web_session.phase == WebPhase.queued:
        return [bot(WAITING_EXECUTIVE)]
    try:
        context = await build_agent_context(session)
        await release_connection(session)
        result = await run_agent(graph, question, context, str(web_session.id))
        touch_last_message(web_session, clock)
        # Escribir texto libre cancela una oferta de ejecutivo pendiente: se atiende como pregunta nueva.
        reset_to_bot(web_session)
        if result.outcome == "mixed_scope":
            replies: list[ServerMessage] = [bot(MIXED_SCOPE)]
        elif result.reply is not None:
            replies = [bot(result.reply)]
        else:
            replies = await offer_human_or_channels(session, web_session, question, clock)
        await commit(session)
        return replies
    except LlmNotConfiguredError:
        return [unavailable()]
    except LlmUnavailableError as exc:
        logger.error("El proveedor del LLM no respondió: %s", exc)
        return [unavailable()]
    except DatabaseUnavailableError as exc:
        logger.error("Base de datos no disponible durante el chat web: %s", exc)
        return [unavailable()]

async def handle_request_human(session: AsyncSession, web_session: WebSession, clock: Clock) -> list[ServerMessage]:
    if web_session.phase in (WebPhase.queued, WebPhase.live):
        return []
    replies = await offer_human_or_channels(session, web_session, web_session.pending_question or HUMAN_REQUESTED, clock)
    await commit(session)
    return replies

async def handle_human_response(session: AsyncSession, web_session: WebSession, accept: bool) -> list[ServerMessage]:
    if web_session.phase != WebPhase.offering_human:
        return []
    answer_offer(web_session, accept)
    await commit(session)
    if accept:
        return [RequestContact(attempt=1)]
    return [bot(OFFER_REJECTED), await official_channels(session)]

async def handle_contact(
    session: AsyncSession, web_session: WebSession, name: str, email: str | None, phone: str | None
) -> list[ServerMessage]:
    if web_session.phase != WebPhase.collecting_contact:
        return []
    question = web_session.pending_question or HUMAN_REQUESTED
    result = submit_contact(web_session, name, email, phone)
    if result.outcome == "queued":
        await enqueue(session, web_session.id, result.name, result.contact, question)
    await commit(session)
    if result.outcome == "retry":
        return [RequestContact(attempt=web_session.contact_attempts + 1)]
    if result.outcome == "exhausted":
        return [bot(CONTACT_EXHAUSTED), await official_channels(session)]
    return [Queued()]

async def offer_human_or_channels(
    session: AsyncSession, web_session: WebSession, question: str, clock: Clock
) -> list[ServerMessage]:
    reply = await ExternalStrategy(session, clock).on_no_answer(NoAnswerContext(question, []))
    if reply.offer_human:
        start_offer(web_session, question)
        return [bot(reply.text), OfferHuman()]
    return [bot(reply.text), OfficialChannels(channels=[Channel(label=label, value=value) for label, value in reply.channels])]

async def official_channels(session: AsyncSession) -> OfficialChannels:
    channels = await get_official_channels(session)
    return OfficialChannels(channels=[Channel(label=channel.label, value=channel.value) for channel in channels])

def bot(text: str) -> TextMessage:
    return TextMessage(from_="bot", text=text)

def unavailable() -> ErrorMessage:
    return ErrorMessage(code="service_unavailable", text=UNAVAILABLE)
