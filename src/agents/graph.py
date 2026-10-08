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
from src.agents.audit import GENERIC_REFUSAL, INTERNAL_NAMES, review
from src.agents.behavior import Clarification
from src.agents.coordinator import CoordinatorToolbox, CoordinatorTurn, run_coordinator
from src.agents.llm import AgentLLM, AreaInfo, CallBudget, ProcedureHit, build_coordinator_messages
from src.agents.retriever import Retriever
from src.agents.scope_agent import ScopeReport, ScopeRequest, run_scope_agent
from src.agents.strategies import Notifier
from src.models.business_area import AreaScope
from src.services.area_notifier import Requester
from src.services.business_data import AreaTopics, get_agent_prompt, get_area_topics, get_areas
from src.services.property import get_int_property

logger = logging.getLogger(__name__)

Outcome = Literal["answered", "rejected", "offer_human", "official_channels", "offer_accepted", "offer_declined",
                  "notification_failed"]
# Motivos del control posterior que se corrigen con un reintento; una fuga nunca se reintenta.
RETRYABLE = ("dato personal", "promesa de seguimiento", "acción no realizada")
RETRY_NOTE = ("[Nota del sistema, no del usuario] Tu respuesta anterior no puede enviarse: {problems}. Reescríbela sin "
              "datos personales que no vengan de la información de las áreas, sin prometer avisos ni seguimientos y sin "
              "afirmar acciones que no hayas hecho con una herramienta en este mensaje.")

@dataclass(frozen=True)
class Catalog:
    areas: list[AreaInfo]  # solo las del ámbito del grafo: el contenido del otro ámbito nunca llega al modelo
    coordinator_prompt: str  # el coordinador conversa sin conocer las áreas: su prompt no las nombra
    scope_prompt: str  # agente de ámbito: decide a qué áreas corresponde la consulta
    area_rules: str  # reglas comunes de todas las áreas
    persona: str | None = None  # tono del asistente del canal; se lee en cada mensaje para aplicar los cambios de la BD
    topics: dict[int, AreaTopics] = field(default_factory=dict)  # temas y trámites de cada área, sin su contenido
    other_area_names: list[str] = field(default_factory=list)  # áreas del otro ámbito: el web nunca debe nombrarlas

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
    offer_pending: bool = False  # el cliente web tiene una oferta de ejecutivo sin responder
    max_steps: int = 4  # pasos del bucle de cada agente de área
    max_model_calls: int = 100  # llamadas al modelo por mensaje entre todos los agentes
    fallback_space: Callable[[], Awaitable[str | None]] | None = None  # space general del canal interno
    is_open: Callable[[], Awaitable[bool]] | None = None  # horario de atención del chat web

@dataclass(frozen=True)
class AgentResult:
    outcome: Outcome
    reply: str | None
    areas: list[AreaInfo]  # áreas en las que se apoyó la respuesta

class AgentInput(TypedDict):
    messages: list[BaseMessage]

def merge_attempts(current: dict[int, int], update: dict[int, int]) -> dict[int, int]:
    return {**current, **update}

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    # Persisten entre mensajes del mismo hilo.
    pending_area_id: int | None
    pending_procedure_id: int | None
    procedure_attempts: Annotated[dict[int, int], merge_attempts]
    clarifications: dict[str, Clarification]  # de la spec 002: los hilos anteriores aún lo traen; ya no se usa
    selected_areas: list[AreaInfo]
    outcome: Outcome | None
    reply: str | None

AgentGraph = CompiledStateGraph[AgentState, AgentContext, AgentInput, AgentState]

# Tipos propios que viajan en el estado: LangGraph exige registrarlos para deserializarlos del checkpointer. Los de la
# aclaración de la spec 002 se mantienen para poder leer los hilos guardados antes de la spec 004.
CHECKPOINT_TYPES = [
    ("src.agents.llm", "AreaInfo"),
    ("src.models.business_area", "AreaScope"),
    ("src.agents.behavior", "Candidate"),
    ("src.agents.behavior", "Clarification"),
    ("src.agents.behavior", "ClarifyOption"),
    ("src.agents.sub_agent", "AreaAnswer"),
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

def procedure_state(toolbox: CoordinatorToolbox) -> dict:
    """Estado del procedimiento tras el turno: sigue en curso solo si el área sigue pidiendo datos."""
    updates: dict = {"procedure_attempts": toolbox.attempts}
    answer = toolbox.procedure
    if answer is None or answer.procedure_id is None:
        return updates
    if answer.kind == "procedure_ask":
        return updates | {"pending_area_id": answer.area.id, "pending_procedure_id": answer.procedure_id}
    updates = updates | {"pending_area_id": None, "pending_procedure_id": None}
    if answer.kind == "gave_up":
        updates["procedure_attempts"] = {**toolbox.attempts, answer.procedure_id: 0}
    return updates

def build_graph(scope: AreaScope, checkpointer: BaseCheckpointSaver | None = None) -> AgentGraph:
    async def respond(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
        context = runtime.context
        *history, last = state["messages"]
        question = text_of(last)
        catalog = await context.load_catalog(scope)
        pending = await pending_procedure(state, {area.id: area for area in catalog.areas}, context)
        budget = CallBudget(context.max_model_calls)

        async def consult(query: str) -> ScopeReport:
            # El ámbito lo fija el canal: el coordinador nunca elige a qué agente de ámbito consulta.
            return await run_scope_agent(context.llm, context.retriever, ScopeRequest(
                scope=scope, areas=catalog.areas, topics=catalog.topics, prompt=catalog.scope_prompt,
                rules=catalog.area_rules, question=query, history=history, pending=pending,
                attempts=state.get("procedure_attempts") or {}, requester=context.requester, notifier=context.notifier,
                history_messages=context.history_messages, max_attempts=context.max_attempts,
                max_steps=context.max_steps, original=question), budget)

        toolbox = CoordinatorToolbox(scope, consult, context.notifier, context.requester, question,
                                     context.fallback_space, context.is_open, context.offer_pending)
        messages = build_coordinator_messages(catalog.coordinator_prompt, catalog.persona, context.offer_pending,
                                              pending.name if pending is not None else None, history, question,
                                              context.history_messages)
        turn = await run_coordinator(context.llm, toolbox, messages, budget)
        prompts = [catalog.coordinator_prompt, catalog.scope_prompt, catalog.area_rules, catalog.persona or "",
                   *(area.system_prompt or "" for area in catalog.areas)]
        # El cliente web nunca debe ver nombres de áreas internas; en Google Chat las áreas son de su ámbito.
        names = INTERNAL_NAMES + (catalog.other_area_names if scope == AreaScope.external else [])
        problems = review(turn.text, prompts, names, toolbox.evidence, toolbox.delivered)
        if problems and all(problem.startswith(RETRYABLE) for problem in problems):
            logger.info("Se pide reescribir la respuesta del coordinador: %s", ", ".join(problems))
            retry = [*messages, AIMessage(turn.text), HumanMessage(RETRY_NOTE.format(problems=", ".join(problems)))]
            turn = await run_coordinator(context.llm, toolbox, retry, budget)
            problems = review(turn.text, prompts, names, toolbox.evidence, toolbox.delivered)
        updates = procedure_state(toolbox)
        if problems:
            # El texto rechazado no se envía ni queda en la memoria del hilo.
            logger.warning("Respuesta del coordinador sustituida por el control posterior: %s", ", ".join(problems))
            return updates | finish("rejected", memory=GENERIC_REFUSAL)
        return updates | finish(await outcome_of(turn), turn.text, [answer.area for answer in toolbox.answers])

    async def outcome_of(turn: CoordinatorTurn) -> Outcome:
        toolbox = turn.toolbox
        if toolbox.notification_failed:
            return "notification_failed"
        if scope == AreaScope.internal:
            return "answered"
        if toolbox.offer_answer is not None:
            return "offer_accepted" if toolbox.offer_answer else "offer_declined"
        gave_up = toolbox.procedure is not None and toolbox.procedure.kind == "gave_up"
        unanswered = toolbox.consulted and not toolbox.evidence and not toolbox.catalog_given
        # Sin información oficial para el cliente, el web ofrece un ejecutivo aunque el coordinador no lo pida.
        if toolbox.offer is None and (gave_up or unanswered):
            await toolbox.offer_executive()
        if toolbox.offer is not None:
            return "offer_human" if toolbox.offer == "human" else "official_channels"
        return "answered"

    graph = StateGraph(AgentState, context_schema=AgentContext, input_schema=AgentInput)
    graph.add_node("respond", respond)
    graph.add_edge(START, "respond")
    graph.add_edge("respond", END)
    return graph.compile(checkpointer=checkpointer)

async def pending_procedure(state: AgentState, areas: dict[int, AreaInfo], context: AgentContext) -> ProcedureHit | None:
    area_id, procedure_id = state.get("pending_area_id"), state.get("pending_procedure_id")
    if area_id not in areas or procedure_id is None:
        return None
    return await context.retriever.get_procedure(area_id, procedure_id)

async def run_agent(graph: AgentGraph, question: str, context: AgentContext, thread_id: str | None = None) -> AgentResult:
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}} if thread_id else {}
    state = await graph.ainvoke({"messages": [HumanMessage(question)]}, config, context=context)
    return AgentResult(state["outcome"], state["reply"], state["selected_areas"])

async def load_catalog(session: AsyncSession, scope: AreaScope) -> Catalog:
    areas = await get_areas(session, scope)
    keys = (f"{scope}_coordinator", f"{scope}_agent", "area_rules")
    prompts = {key: await get_agent_prompt(session, key) for key in keys}
    missing = [key for key, value in prompts.items() if value is None]
    if missing:
        logger.warning("Faltan prompts en agent_prompt: %s", ", ".join(missing))
    topics = await get_area_topics(session, [area.id for area in areas],
                                   await get_int_property(session, "scope_topics_per_area", 50))
    # El auditor del web prohíbe los nombres de las áreas internas; en Google Chat no hace falta la otra lista.
    other_names = [area.name for area in await get_areas(session, AreaScope.internal)] if scope == AreaScope.external else []
    return Catalog(
        [AreaInfo(area.id, area.name, area.description, area.scope, area.system_prompt, area.chat_space) for area in areas],
        prompts[f"{scope}_coordinator"] or "",
        prompts[f"{scope}_agent"] or "",
        prompts["area_rules"] or "",
        await get_agent_prompt(session, f"{scope}_persona"),
        topics,
        other_names,
    )
