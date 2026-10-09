"""Grafo del patrón coordinador (plan, D1): route → (fin si es directa) → retrieve → sub_agent × N en paralelo →
synthesize. Un mensaje directo hace 1 llamada al modelo; uno con N áreas, 2 + N (RNF-6)."""
import logging
import operator
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any
from langchain_core.messages import BaseMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Send
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.coordinator import route, synthesize
from src.agents.llm import (AreaResult, Catalog, CoordinatorModel, FaqHit, KnowledgeSource, RoutingDecision,
                            SubAgentModel, Subtask)
from src.agents.sub_agent import run_sub_agent
from src.agents.tools.access import can_use_tools, restricted_note
from src.agents.tools.faq_search import faq_search_tool
from src.agents.tools.available import TOOLS
from src.agents.tools.registry import AreaTool, ToolContext, tools_for
from src.services.property import Properties

logger = logging.getLogger(__name__)

def log_step(step: str, started: float) -> None:
    # Duración de cada paso, sin textos (RNF-3), para medir el presupuesto de latencia (plan, sección 7).
    logger.info("Paso %s: %.2f s", step, time.perf_counter() - started)

@dataclass(frozen=True)
class Limits:
    max_areas: int
    faqs_per_search: int
    sub_agent_max_steps: int
    sub_agent_timeout: float

@dataclass(frozen=True)
class AgentContext:
    """Dependencias de un mensaje: el catálogo del canal y los modelos se resuelven fuera del grafo."""
    catalog: Catalog
    coordinator: CoordinatorModel
    sub_agent: SubAgentModel
    knowledge: KnowledgeSource
    limits: Limits
    registry: Mapping[str, AreaTool] = field(default_factory=lambda: TOOLS)
    # Quién escribe (None en el web), la configuración del mensaje y cómo abrir sesiones propias (spec 002).
    requester: str | None = None
    properties: Properties = field(default_factory=lambda: Properties({}))
    session_factory: Callable[[], AsyncSession] | None = None

@dataclass
class AgentState:
    question: str
    history: list[BaseMessage]
    decision: RoutingDecision = field(default_factory=lambda: RoutingDecision("areas"))
    faqs: dict[int, list[FaqHit]] = field(default_factory=dict)
    # Cada sub-agente agrega su resultado; el reducer los junta al terminar el paso paralelo.
    results: Annotated[list[AreaResult], operator.add] = field(default_factory=list)
    reply: str = ""

@dataclass
class SubAgentInput:
    subtask: Subtask
    faqs: list[FaqHit]

async def route_node(state: AgentState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    context, started = runtime.context, time.perf_counter()
    decision = await route(context.coordinator, context.catalog, state.history, state.question,
                           context.limits.max_areas)
    log_step("route", started)
    return {"decision": decision, "reply": decision.reply}

def after_route(state: AgentState) -> str:
    return END if state.decision.kind == "direct" else "retrieve"

async def retrieve_node(state: AgentState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    subtasks = state.decision.subtasks
    if not subtasks:
        return {"faqs": {}}
    started = time.perf_counter()
    faqs = await runtime.context.knowledge.search(subtasks, runtime.context.limits.faqs_per_search)
    log_step("retrieve", started)
    return {"faqs": faqs}

def fan_out(state: AgentState) -> list[Send] | str:
    subtasks = state.decision.subtasks
    if not subtasks:
        return "synthesize"
    # Cada sub-agente recibe solo su subtarea y las FAQ de su área (RF-7, RNF-7).
    return [Send("sub_agent", SubAgentInput(subtask, state.faqs.get(subtask.area_id, [])))
            for subtask in subtasks]

async def sub_agent_node(state: SubAgentInput, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    context, subtask = runtime.context, state.subtask
    area = context.catalog.area(subtask.area_id)
    if area is None:  # route ya lo descartó; se mantiene por si el catálogo cambia de forma
        return {"results": [AreaResult(subtask.area_id, "", subtask.query, False)]}
    started = time.perf_counter()
    area_tools = tools_for(area.name, area.tools, context.registry)
    # Acceso decidido antes de llamar al modelo: lo que no recibe, no lo puede ejecutar (spec 002, RF-4 a RF-7).
    allowed = can_use_tools(area, context.requester)
    # buscar_faq la reciben todos, en ambos canales y habilitados o no (spec 002, RF-25).
    faq_search = faq_search_tool(area.id, context.knowledge, context.limits.faqs_per_search)
    tools = [faq_search, *area_tools] if allowed else [faq_search]
    note = restricted_note(area_tools) if area_tools and not allowed else None
    tool_context = ToolContext(context.requester, context.properties, context.session_factory)
    result = await run_sub_agent(context.sub_agent, context.catalog, area, state.faqs, subtask, tools,
                                 context.limits.sub_agent_max_steps, context.limits.sub_agent_timeout,
                                 tool_context, note)
    log_step(f"sub_agent {area.name}", started)
    return {"results": [result]}

async def synthesize_node(state: AgentState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    context, started = runtime.context, time.perf_counter()
    # Los sub-agentes terminan en cualquier orden: se presentan en el orden de las subtareas.
    order = {subtask.area_id: index for index, subtask in enumerate(state.decision.subtasks)}
    results = sorted(state.results, key=lambda result: order.get(result.area_id, len(order)))
    reply = await synthesize(context.coordinator, context.catalog, state.history, state.question, results)
    log_step("synthesize", started)
    return {"reply": reply}

def build_graph():
    graph = StateGraph(AgentState, context_schema=AgentContext)
    graph.add_node("route", route_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("sub_agent", sub_agent_node, input_schema=SubAgentInput)
    graph.add_node("synthesize", synthesize_node)
    graph.add_edge(START, "route")
    graph.add_conditional_edges("route", after_route, ["retrieve", END])
    graph.add_conditional_edges("retrieve", fan_out, ["sub_agent", "synthesize"])
    graph.add_edge("sub_agent", "synthesize")
    graph.add_edge("synthesize", END)
    return graph.compile()

GRAPH = build_graph()

async def run_graph(context: AgentContext, history: Sequence[BaseMessage], question: str) -> str:
    state = await GRAPH.ainvoke(AgentState(question, list(history)), context=context)
    return state["reply"]
