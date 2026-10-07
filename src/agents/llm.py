import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol, cast
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.business_area import AreaScope
from src.services.property import get_float_property, get_str_property
from src.utils.exceptions.agent import LlmNotConfiguredError, LlmUnavailableError
from src.utils.exceptions.property import PropertyNotFoundError

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class AreaInfo:
    id: int
    name: str
    description: str
    scope: AreaScope
    system_prompt: str | None
    owner_email: str | None = None

@dataclass(frozen=True)
class FaqHit:
    question: str
    answer: str
    similarity: float

@dataclass(frozen=True)
class Classification:
    area_ids: list[int]
    wants_human: bool

@dataclass(frozen=True)
class AreaAnswer:
    area_id: int
    area_name: str
    text: str | None  # None: el área no pudo responder

class AgentLLM(Protocol):
    async def classify(self, prompt: str, question: str, areas: list[AreaInfo], history: list[BaseMessage]) -> Classification: ...
    async def answer(self, area: AreaInfo, rules: str, question: str, faqs: list[FaqHit], history: list[BaseMessage]) -> AreaAnswer: ...
    async def combine(self, prompt: str, question: str, parts: list[AreaAnswer]) -> str: ...

class ClassificationOutput(BaseModel):
    area_ids: list[int] = Field(description="Ids de las áreas a las que corresponde la pregunta; vacío si ninguna")
    wants_human: bool = Field(description="True si el usuario pide hablar con una persona")

class AnswerOutput(BaseModel):
    answered: bool = Field(description="False si las preguntas frecuentes no responden la pregunta")
    text: str = Field(description="Respuesta al usuario, basada solo en las preguntas frecuentes")

def build_classify_messages(prompt: str, question: str, areas: list[AreaInfo], history: list[BaseMessage]) -> list[BaseMessage]:
    catalog = "\n".join(f"- id {area.id}: {area.name}. {area.description}" for area in areas)
    return [SystemMessage(f"{prompt}\n\nÁreas disponibles:\n{catalog}"), *history, HumanMessage(question)]

def build_answer_messages(
    area: AreaInfo, rules: str, question: str, faqs: list[FaqHit], history: list[BaseMessage]
) -> list[BaseMessage]:
    # Las instrucciones (prompt del área y reglas comunes) vienen de la BD; aquí solo se añaden las FAQ recuperadas.
    faq_text = "\n\n".join(f"Pregunta: {faq.question}\nRespuesta: {faq.answer}" for faq in faqs)
    instructions = f"{area.system_prompt}\n\n{rules}\n\nPreguntas frecuentes:\n\n{faq_text}"
    return [SystemMessage(instructions), *history, HumanMessage(question)]

def build_combine_messages(prompt: str, question: str, parts: list[AreaAnswer]) -> list[BaseMessage]:
    answered = "\n\n".join(f"{part.area_name}: {part.text}" for part in parts if part.text is not None)
    unanswered = ", ".join(part.area_name for part in parts if part.text is None)
    content = f"Pregunta del usuario: {question}\n\nRespuestas de las áreas:\n{answered}"
    if unanswered:
        content += f"\n\nÁreas sin respuesta: {unanswered}"
    # Cómo combinar e indicar lo que falta lo dice el prompt del agente (BD).
    return [SystemMessage(prompt), HumanMessage(content)]

class GeminiAgentLLM:
    def __init__(self, chat: BaseChatModel):
        self._chat = chat

    async def classify(self, prompt: str, question: str, areas: list[AreaInfo], history: list[BaseMessage]) -> Classification:
        output = cast(ClassificationOutput, await self._invoke_structured(
            ClassificationOutput, build_classify_messages(prompt, question, areas, history)))
        return Classification(output.area_ids, output.wants_human)

    async def answer(self, area: AreaInfo, rules: str, question: str, faqs: list[FaqHit], history: list[BaseMessage]) -> AreaAnswer:
        output = cast(AnswerOutput, await self._invoke_structured(
            AnswerOutput, build_answer_messages(area, rules, question, faqs, history)))
        return AreaAnswer(area.id, area.name, output.text if output.answered else None)

    async def combine(self, prompt: str, question: str, parts: list[AreaAnswer]) -> str:
        try:
            message = await self._chat.ainvoke(build_combine_messages(prompt, question, parts))
        except Exception as exc:
            raise LlmUnavailableError(str(exc)) from exc
        return str(message.text)

    async def _invoke_structured(self, schema: type[BaseModel], messages: list[BaseMessage]) -> object:
        try:
            return await self._chat.with_structured_output(schema).ainvoke(messages)
        except Exception as exc:
            raise LlmUnavailableError(str(exc)) from exc

async def get_llm_property(session: AsyncSession, key: str) -> str:
    try:
        value = await get_str_property(session, key)
    except PropertyNotFoundError:
        value = ""
    if not value.strip():
        logger.error("LLM no configurado: falta la property %s", key)
        raise LlmNotConfiguredError(key)
    return value

async def build_gemini_llm(session: AsyncSession) -> GeminiAgentLLM:
    model = await get_llm_property(session, "gemini_model")
    api_key = await get_llm_property(session, "gemini_api_key")
    timeout = await get_float_property(session, "llm_timeout_seconds", 20)
    return GeminiAgentLLM(gemini_chat(model, api_key, timeout))

# Se reutiliza el cliente mientras no cambie la configuración: uno nuevo por mensaje abre conexiones TLS nuevas y,
# con 50 sesiones a la vez, parte de ellas fallan al conectar.
@lru_cache(maxsize=4)
def gemini_chat(model: str, api_key: str, timeout: float) -> ChatGoogleGenerativeAI:
    # Un solo reintento: con más, un proveedor caído tardaría minutos en responder "no disponible".
    return ChatGoogleGenerativeAI(model=model, google_api_key=SecretStr(api_key), timeout=timeout, max_retries=1)
