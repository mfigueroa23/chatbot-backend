import logging
from functools import partial
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.graph import AgentContext, build_graph, load_catalog, run_agent
from src.agents.llm import build_gemini_llm
from src.agents.retriever import build_faq_retriever
from src.agents.strategies import InternalStrategy, NoAnswerContext
from src.database.session import SessionLocal
from src.models.business_area import AreaScope
from src.services.mailer import Mailer
from src.services.message_validation import MAX_MESSAGE_LENGTH, validate_user_message
from src.utils.exceptions.agent import LlmNotConfiguredError, LlmUnavailableError
from src.utils.exceptions.database import DatabaseUnavailableError
from src.utils.exceptions.message import EmptyMessageError, MessageTooLongError

logger = logging.getLogger(__name__)

EMPTY_MESSAGE = "Por favor, escribe tu consulta."
TOO_LONG_MESSAGE = f"Tu mensaje supera el máximo de {MAX_MESSAGE_LENGTH} caracteres. Por favor, acórtalo."
UNAVAILABLE = "El servicio no está disponible en este momento. Por favor, intenta más tarde."
MIXED_SCOPE = "Tu pregunta mezcla temas de distintas áreas. Por favor, reformúlala para poder ayudarte."

# El canal interno no tiene memoria: su grafo no lleva checkpointer.
internal_graph = build_graph(AreaScope.internal)

async def build_agent_context(session: AsyncSession) -> AgentContext:
    return AgentContext(
        llm=await build_gemini_llm(session),
        retriever=await build_faq_retriever(session, SessionLocal),
        load_catalog=partial(load_catalog, session),
    )

async def handle_internal_message(session: AsyncSession, text: str, user_name: str | None, user_email: str | None) -> str:
    try:
        question = validate_user_message(text)
    except EmptyMessageError:
        return EMPTY_MESSAGE
    except MessageTooLongError:
        return TOO_LONG_MESSAGE
    try:
        result = await run_agent(internal_graph, question, await build_agent_context(session))
        if result.outcome == "mixed_scope":
            return MIXED_SCOPE
        if result.reply is not None:
            return result.reply
        strategy = InternalStrategy(session, Mailer(session))
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
