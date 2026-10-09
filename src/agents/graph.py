"""Grafo del patrón coordinador (plan, D1): route → (fin si es directa) → retrieve → sub_agent × N en paralelo →
synthesize. Un mensaje directo hace 1 llamada al modelo; uno con N áreas, 2 + N (RNF-6)."""
import operator
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any
from langchain_core.messages import BaseMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Send
from src.agents.coordinator import route, synthesize
from src.agents.llm import (AreaResult, Catalog, CoordinatorModel, FaqHit, KnowledgeSource, RoutingDecision,
                            SubAgentModel, Subtask)
from src.agents.sub_agent import run_sub_agent
from src.agents.tools import TOOLS, AreaTool, tools_for

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
    context = runtime.context
    decision = await route(context.coordinator, context.catalog, state.history, state.question,
                           context.limits.max_areas)
    return {"decision": decision, "reply": decision.reply}

def after_route(state: AgentState) -> str:
    return END if state.decision.kind == "direct" else "retrieve"

async def retrieve_node(state: AgentState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    subtasks = state.decision.subtasks
    if not subtasks:
        return {"faqs": {}}
    return {"faqs": await runtime.context.knowledge.search(subtasks, runtime.context.limits.faqs_per_search)}

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
    tools = tools_for(area.name, area.tools, context.registry)
    result = await run_sub_agent(context.sub_agent, context.catalog, area, state.faqs, subtask, tools,
                                 context.limits.sub_agent_max_steps, context.limits.sub_agent_timeout)
    return {"results": [result]}

async def synthesize_node(state: AgentState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    context = runtime.context
    # Los sub-agentes terminan en cualquier orden: se presentan en el orden de las subtareas.
    order = {subtask.area_id: index for index, subtask in enumerate(state.decision.subtasks)}
    results = sorted(state.results, key=lambda result: order.get(result.area_id, len(order)))
    reply = await synthesize(context.coordinator, context.catalog, state.history, state.question, results)
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
