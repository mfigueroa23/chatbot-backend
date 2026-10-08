import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated, Literal, TypedDict
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.audit import GENERIC_REFUSAL, INTERNAL_NAMES, find_leaks, strip_citations
from src.agents.llm import AgentLLM, AgentReply, AreaInfo, AreaSection, FaqHit, ProcedureHit, build_reply_messages
from src.agents.procedure_flow import handle_procedure
from src.agents.retriever import Retriever
from src.agents.strategies import Notifier
from src.models.business_area import AreaScope
from src.services.area_notifier import Requester
from src.services.business_data import get_agent_prompt, get_areas
from src.services.procedures import web_contact_fields

logger = logging.getLogger(__name__)

Outcome = Literal["answered", "no_answer", "mixed_scope", "wants_human", "notification_failed", "rejected"]
# Mensajes fijos de cada canal: viven en agent_prompt con la key "<ámbito>_<tipo>".
FIXED_KINDS = ("greeting", "closing", "off_topic")

@dataclass(frozen=True)
class Catalog:
    areas: list[AreaInfo]  # solo las del ámbito del grafo: el contenido del otro ámbito nunca llega al modelo
    agent_prompt: str
    area_rules: str  # reglas comunes de todas las áreas
    fixed: dict[str, str | None] = field(default_factory=dict)  # texto de cada mensaje fijo; None si falta en la BD
    area_names: list[str] = field(default_factory=list)  # todas las áreas activas del ámbito, tengan prompt o no

@dataclass(frozen=True)
class AgentContext:
    """Dependencias de cada mensaje: el grafo se compila una vez y la configuración puede cambiar en la BD."""
    llm: AgentLLM
    retriever: Retriever
    load_catalog: Callable[[AreaScope], Awaitable[Catalog]]
    notifier: Notifier
    requester: Requester | None  # None en el canal web: el cliente es anónimo y da sus datos en el procedimiento
    history_messages: int = 20
    max_attempts: int = 3

@dataclass(frozen=True)
class AgentResult:
    outcome: Outcome
    reply: str | None
    areas: list[AreaInfo]  # áreas en las que se apoyó la respuesta (o a las que correspondía la consulta)

class AgentInput(TypedDict):
    messages: list[BaseMessage]

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    # Procedimiento en curso: se recuerda entre mensajes del mismo hilo aunque la búsqueda ya no lo devuelva.
    pending_area_id: int | None
    pending_procedure_id: int | None
    procedure_attempts: dict[int, int]
    selected_areas: list[AreaInfo]
    outcome: Outcome | None
    reply: str | None

AgentGraph = CompiledStateGraph[AgentState, AgentContext, AgentInput, AgentState]

# Tipos propios que viajan en el estado: LangGraph exige registrarlos para deserializarlos del checkpointer.
CHECKPOINT_TYPES = [
    ("src.agents.llm", "AreaInfo"),
    ("src.models.business_area", "AreaScope"),
]

def checkpoint_serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)

def text_of(message: BaseMessage) -> str:
    # message.text es una subclase de str que el cliente de Gemini serializa mal (500 en los embeddings).
    return str(message.text)

def finish(outcome: Outcome, reply: str | None = None, areas: list[AreaInfo] | None = None, memory: str | None = None) -> dict:
    remembered = reply or memory
    return {
        "outcome": outcome,
        "reply": reply,
        "selected_areas": areas or [],
        "messages": [AIMessage(remembered)] if remembered else [],
    }

def audited(text: str, prompts: list[str], used: list[AreaInfo]) -> dict:
    leaks = find_leaks(text, prompts, INTERNAL_NAMES)
    if leaks:
        # El texto filtrado no se envía ni queda en la memoria del hilo.
        logger.warning("Respuesta sustituida por el auditor: %s", ", ".join(leaks))
        return finish("rejected", memory=GENERIC_REFUSAL)
    return finish("answered", text, used)

def build_graph(scope: AreaScope, checkpointer: BaseCheckpointSaver | None = None) -> AgentGraph:
    async def answer(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
        context = runtime.context
        *history, last = state["messages"]
        question = text_of(last)
        catalog = await context.load_catalog(scope)
        # Un área sin prompt no puede responder: su contenido no llega al modelo.
        areas = {area.id: area for area in catalog.areas if area.system_prompt}
        await context.retriever.refresh_stale_embeddings(list(areas))
        # El mensaje anterior del usuario da contexto a las preguntas de seguimiento sin otra llamada al modelo.
        previous = next((text_of(message) for message in reversed(history) if isinstance(message, HumanMessage)), None)
        knowledge = await context.retriever.search_scope(scope, f"{previous}\n{question}" if previous else question)
        faqs = [faq for faq in knowledge.faqs if faq.area_id in areas]
        procedures = [procedure for procedure in knowledge.procedures if procedure.area_id in areas]
        if (faqs or procedures) and knowledge.other_scope_match:
            return finish("mixed_scope")

        pending_area_id, pending_id = state.get("pending_area_id"), state.get("pending_procedure_id")
        pending = None
        if pending_area_id in areas and pending_id is not None:
            pending = await context.retriever.get_procedure(pending_area_id, pending_id)
        sections = [AreaSection(area, [f for f in faqs if f.area_id == area.id], [p for p in procedures if p.area_id == area.id])
                    for area in areas.values()
                    if any(f.area_id == area.id for f in faqs) or any(p.area_id == area.id for p in procedures)]
        extra_fields = web_contact_fields() if scope == AreaScope.external else []
        reply = await context.llm.respond(build_reply_messages(
            catalog.agent_prompt, catalog.area_rules, sections, pending, history, question, context.history_messages, extra_fields))

        prompts = [catalog.agent_prompt, catalog.area_rules, *(area.system_prompt or "" for area in catalog.areas)]
        used_areas = [section.area for section in sections]
        match reply.kind:
            case "manipulation":
                return finish("rejected", memory=GENERIC_REFUSAL)
            case "wants_human":
                return finish("wants_human", areas=used_areas)
            case "answer":
                return answered(reply, faqs, areas, prompts, used_areas)
            case "procedure":
                return await procedure_step(reply, question, areas, procedures, pending, prompts, state, context)
        return finish("no_answer", areas=used_areas)

    def answered(reply: AgentReply, faqs: list[FaqHit], areas: dict[int, AreaInfo], prompts: list[str],
                 used_areas: list[AreaInfo]) -> dict:
        retrieved = {faq.id: faq for faq in faqs}
        # Guardarraíl: solo vale una respuesta que cita FAQ recuperadas para este mensaje.
        if not reply.faq_ids or any(faq_id not in retrieved for faq_id in reply.faq_ids):
            logger.info("Respuesta descartada: no se apoya en FAQ recuperadas")
            return finish("no_answer", areas=used_areas)
        cited = list({retrieved[faq_id].area_id: areas[retrieved[faq_id].area_id] for faq_id in reply.faq_ids}.values())
        return audited(strip_citations(reply.text), prompts, cited)

    async def procedure_step(
        reply: AgentReply, question: str, areas: dict[int, AreaInfo], procedures: list[ProcedureHit],
        pending: ProcedureHit | None, prompts: list[str], state: AgentState, context: AgentContext,
    ) -> dict:
        candidates = {procedure.id: procedure for procedure in procedures}
        if pending is not None:
            candidates.setdefault(pending.id, pending)
        procedure = candidates.get(reply.procedure_id) if reply.procedure_id is not None else None
        if procedure is None:
            logger.info("Respuesta descartada: el procedimiento no fue recuperado ni está en curso")
            return finish("no_answer")
        area = areas[procedure.area_id]
        result = await handle_procedure(
            procedure, area, reply.data, context.requester, question, state.get("procedure_attempts") or {},
            context.max_attempts, context.notifier, strip_citations(reply.text), pending is None or pending.id != procedure.id)
        attempts = {"procedure_attempts": result.attempts}
        if result.kind == "ask":
            updates = audited(result.text or "", prompts, [area])
            if updates["outcome"] == "answered":
                updates |= {"pending_area_id": area.id, "pending_procedure_id": procedure.id}
            return updates | attempts
        cleared = {"pending_area_id": None, "pending_procedure_id": None} | attempts
        if result.kind == "sent":
            return finish("answered", result.text, [area]) | cleared
        if result.kind == "failed":
            return finish("notification_failed", areas=[area]) | cleared
        # Tras los intentos permitidos se aplica el flujo de sin respuesta del canal.
        return finish("no_answer", areas=[area]) | cleared | {"procedure_attempts": {**result.attempts, procedure.id: 0}}

    graph = StateGraph(AgentState, context_schema=AgentContext, input_schema=AgentInput)
    graph.add_node("answer", answer)
    graph.add_edge(START, "answer")
    graph.add_edge("answer", END)
    return graph.compile(checkpointer=checkpointer)

async def run_agent(graph: AgentGraph, question: str, context: AgentContext, thread_id: str | None = None) -> AgentResult:
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}} if thread_id else {}
    state = await graph.ainvoke({"messages": [HumanMessage(question)]}, config, context=context)
    return AgentResult(state["outcome"], state["reply"], state["selected_areas"])

async def load_catalog(session: AsyncSession, scope: AreaScope) -> Catalog:
    areas = await get_areas(session, scope)
    prompts = {key: await get_agent_prompt(session, key) for key in (f"{scope}_agent", "area_rules")}
    fixed = {kind: await get_agent_prompt(session, f"{scope}_{kind}") for kind in FIXED_KINDS}
    missing = [key for key, value in prompts.items() if value is None]
    if missing:
        logger.warning("Faltan prompts en agent_prompt: %s", ", ".join(missing))
    return Catalog(
        [AreaInfo(area.id, area.name, area.description, area.scope, area.system_prompt, area.chat_space) for area in areas],
        prompts[f"{scope}_agent"] or "",
        prompts["area_rules"] or "",
        fixed,
        [area.name for area in areas],
    )
