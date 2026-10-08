import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol, cast
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.business_area import AreaScope
from src.services.business_data import AreaTopics
from src.services.procedures import FieldSpec
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
    chat_space: str | None = None

@dataclass(frozen=True)
class FaqHit:
    question: str
    answer: str
    similarity: float
    id: int = 0
    area_id: int = 0

@dataclass(frozen=True)
class ProcedureHit:
    id: int
    name: str
    steps: str
    fields: list[FieldSpec]
    similarity: float
    area_id: int = 0

@dataclass(frozen=True)
class AreaSection:
    """Lo que el modelo sabe de un área en este mensaje: su prompt y lo recuperado de ella."""
    area: AreaInfo
    faqs: list[FaqHit]
    procedures: list[ProcedureHit]

@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # esquema JSON de los argumentos

@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]

@dataclass(frozen=True)
class ToolCalls:
    calls: list[ToolCall]
    text: str = ""  # lo que el modelo escribió junto a las llamadas (p. ej. la explicación de un procedimiento)

@dataclass(frozen=True)
class FinalText:
    text: str

AgentStep = ToolCalls | FinalText

@dataclass(frozen=True)
class ScopeDecision:
    """Decisión del agente de ámbito: a qué áreas va la consulta, reformulada, o si el usuario pide el catálogo."""
    area_ids: list[int]
    consulta: str
    catalogo: bool

class AgentLLM(Protocol):
    # Coordinador y agentes de área: un paso del bucle con sus herramientas.
    async def step(self, messages: list[BaseMessage], tools: list[ToolSpec]) -> AgentStep: ...
    # Agente de ámbito: decide en una llamada a qué áreas va la consulta.
    async def decide_scope(self, messages: list[BaseMessage]) -> ScopeDecision: ...

class ScopeOutput(BaseModel):
    area_ids: list[int] = Field(default_factory=list, description=(
        "Ids [A…] de todas las áreas a las que corresponde la consulta, según su descripción y sus temas; vacío si no "
        "corresponde a ninguna"))
    consulta: str = Field(default="", description=(
        "La consulta completa para buscar en esas áreas, reformulada con el contexto de la conversación (p. ej. «¿y de "
        "Remuneraciones?» tras preguntar por el sueldo)"))
    catalogo: bool = Field(default=False, description=(
        "true si el usuario pregunta qué puede consultar o con qué temas puede ayudarle el asistente"))

LANGUAGE_RULE = "Responde siempre en español, aunque el usuario escriba en otro idioma."
AREA_CONTENT = (
    "Trabajas para el coordinador del asistente: no hablas con el usuario. Con la información de tu área, genera el "
    "contenido que responde lo que se pide, completo y sin saludos; el coordinador lo entregará con sus palabras.")

def persona_part(persona: str | None) -> list[str]:
    return [f"Persona del asistente:\n{persona}"] if persona else []

def describe_fields(fields: list[FieldSpec]) -> str:
    return "\n".join(f"- {spec.label} (campo: {spec.name})" for spec in fields) or "- Ninguno"

def describe_procedure(procedure: ProcedureHit, extra_fields: list[FieldSpec]) -> str:
    return (f"[P{procedure.id}] {procedure.name}\nPasos: {procedure.steps}\n"
            f"Datos exigidos:\n{describe_fields(procedure.fields + extra_fields)}")

def describe_section(section: AreaSection, extra_fields: list[FieldSpec]) -> str:
    parts = [f"### Área: {section.area.name}\n{section.area.system_prompt}"]
    if section.faqs:
        parts.append("Preguntas frecuentes:\n" + "\n".join(
            f"[F{faq.id}] Pregunta: {faq.question}\nRespuesta: {faq.answer}" for faq in section.faqs))
    if section.procedures:
        parts.append("Procedimientos:\n" + "\n".join(describe_procedure(p, extra_fields) for p in section.procedures))
    return "\n\n".join(parts)

def history_window(history: list[BaseMessage], size: int) -> list[BaseMessage]:
    # Ventana acotada que empieza en un mensaje del usuario, para no cortar un intercambio por la mitad.
    window = history[-size:] if size > 0 else []
    while window and not isinstance(window[0], HumanMessage):
        window = window[1:]
    return window

def describe_topics(area: AreaInfo, topics: AreaTopics | None, with_id: bool = True) -> str:
    lines = [f"{f'[A{area.id}] ' if with_id else ''}{area.name}: {area.description}"]
    if topics is not None and topics.faqs:
        lines.append("  Temas: " + "; ".join(topics.faqs))
    if topics is not None and topics.procedures:
        lines.append("  Trámites: " + "; ".join(topics.procedures))
    return "\n".join(lines)

def build_scope_messages(
    prompt: str,
    areas: list[AreaInfo],
    pending: ProcedureHit | None,
    history: list[BaseMessage],
    question: str,
    history_messages: int,
    topics: dict[int, AreaTopics] | None = None,
) -> list[BaseMessage]:
    # El agente de ámbito decide con el nombre, la descripción y los temas de cada área: el contenido solo lo ve el
    # agente del área.
    known = topics or {}
    parts = [prompt, "Áreas del canal:\n" + "\n".join(describe_topics(area, known.get(area.id)) for area in areas)]
    if pending is not None:
        parts.append(f"Procedimiento en curso: {pending.name} [A{pending.area_id}]")
    return [SystemMessage("\n\n".join(parts)), *history_window(history, history_messages), HumanMessage(question)]

def build_coordinator_messages(
    prompt: str,
    persona: str | None,
    offer_pending: bool,
    pending_name: str | None,
    history: list[BaseMessage],
    question: str,
    history_messages: int,
) -> list[BaseMessage]:
    # El coordinador conversa sin las áreas en su contexto: las conoce el agente de ámbito al que consulta.
    parts = [prompt, *persona_part(persona)]
    if offer_pending:
        parts.append("Hay una oferta de hablar con un ejecutivo pendiente de respuesta del cliente.")
    if pending_name:
        parts.append(f"Hay un trámite en curso: «{pending_name}». Los datos que entregue el usuario son para ese trámite.")
    parts.append(LANGUAGE_RULE)
    return [SystemMessage("\n\n".join(part for part in parts if part)), *history_window(history, history_messages),
            HumanMessage(question)]

def build_area_messages(
    area: AreaInfo,
    rules: str,
    faqs: list[FaqHit],
    procedures: list[ProcedureHit],
    pending: ProcedureHit | None,
    history: list[BaseMessage],
    question: str,
    history_messages: int,
    extra_fields: list[FieldSpec],
) -> list[BaseMessage]:
    # Solo el prompt y el contenido de esta área: el agente de un área nunca ve los de otra.
    knowledge = describe_section(AreaSection(area, faqs, procedures), extra_fields)
    if not faqs and not procedures:
        knowledge += "\n\nNo se encontró información del área para este mensaje."
    parts = [knowledge, rules, AREA_CONTENT]
    if pending is not None:
        parts.append(f"Procedimiento en curso:\n{describe_procedure(pending, extra_fields)}")
    parts.append(LANGUAGE_RULE)
    return [SystemMessage("\n\n".join(parts)), *history_window(history, history_messages), HumanMessage(question)]

class GeminiAgentLLM:
    def __init__(self, chat: BaseChatModel):
        self._chat = chat

    async def decide_scope(self, messages: list[BaseMessage]) -> ScopeDecision:
        try:
            output = cast(ScopeOutput, await self._chat.with_structured_output(ScopeOutput).ainvoke(messages))
        except Exception as exc:
            raise LlmUnavailableError(str(exc)) from exc
        return ScopeDecision(list(output.area_ids), output.consulta.strip(), output.catalogo)

    async def step(self, messages: list[BaseMessage], tools: list[ToolSpec]) -> AgentStep:
        declarations = [{"name": tool.name, "description": tool.description, "parameters": tool.parameters} for tool in tools]
        try:
            message = await self._chat.bind_tools(declarations).ainvoke(messages)
        except Exception as exc:
            raise LlmUnavailableError(str(exc)) from exc
        if isinstance(message, AIMessage) and message.tool_calls:
            calls = [ToolCall(call["id"] or call["name"], call["name"], dict(call["args"])) for call in message.tool_calls]
            return ToolCalls(calls, str(message.text))
        return FinalText(str(message.text))

class CallBudget:
    """Tope de llamadas al modelo de un mensaje, compartido por el coordinador, el agente de ámbito y las áreas."""

    def __init__(self, limit: int):
        self.limit = limit
        self.used = 0

    def spend(self) -> None:
        if self.used >= self.limit:
            logger.warning("Se agotó el presupuesto de %s llamadas al modelo del mensaje", self.limit)
            raise LlmUnavailableError("presupuesto de llamadas agotado")
        self.used += 1

async def get_llm_property(session: AsyncSession, key: str) -> str:
    try:
        value = await get_str_property(session, key)
    except PropertyNotFoundError:
        value = ""
    if not value.strip():
        logger.error("LLM no configurado: falta la property %s", key)
        raise LlmNotConfiguredError(key)
    return value

async def build_gemini_llm(session: AsyncSession, temperature: float = 0.0) -> GeminiAgentLLM:
    model = await get_llm_property(session, "gemini_model")
    api_key = await get_llm_property(session, "gemini_api_key")
    timeout = await get_float_property(session, "llm_timeout_seconds", 20)
    return GeminiAgentLLM(gemini_chat(model, api_key, timeout, temperature))

# Se reutiliza el cliente mientras no cambie la configuración: uno nuevo por mensaje abre conexiones TLS nuevas y,
# con 50 sesiones a la vez, parte de ellas fallan al conectar.
@lru_cache(maxsize=4)
def gemini_chat(model: str, api_key: str, timeout: float, temperature: float = 0.0) -> ChatGoogleGenerativeAI:
    # Un solo reintento: con más, un proveedor caído tardaría minutos en responder "no disponible".
    # Sin razonamiento para la menor latencia posible. La temperatura la fija cada canal: con 0 los textos redactados
    # serían siempre idénticos.
    return ChatGoogleGenerativeAI(model=model, google_api_key=SecretStr(api_key), timeout=timeout, max_retries=1,
                                  temperature=temperature, thinking_budget=0)
