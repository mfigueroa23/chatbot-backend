import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Literal, TypedDict
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import Send
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.llm import AgentLLM, AreaAnswer, AreaInfo
from src.agents.retriever import Retriever
from src.models.business_area import AreaScope
from src.services.business_data import get_agent_prompt, get_areas

logger = logging.getLogger(__name__)

Outcome = Literal["answered", "partial", "no_answer", "mixed_scope", "wants_human"]

@dataclass(frozen=True)
class Catalog:
    areas: list[AreaInfo]  # de ambos ámbitos: el clasificador los necesita para detectar las preguntas mixtas
    classifier_prompt: str
    agent_prompt: str

@dataclass(frozen=True)
class AgentContext:
    """Dependencias de cada mensaje: el grafo se compila una vez y la configuración puede cambiar en la BD."""
    llm: AgentLLM
    retriever: Retriever
    load_catalog: Callable[[AreaScope], Awaitable[Catalog]]

@dataclass(frozen=True)
class AgentResult:
    outcome: Outcome
    reply: str | None
    areas: list[AreaInfo]  # áreas del ámbito a las que correspondía la pregunta

def merge_answers(current: list[AreaAnswer], update: list[AreaAnswer]) -> list[AreaAnswer]:
    # Una lista vacía reinicia las respuestas al empezar cada mensaje; el fan-out las va acumulando.
    return current + update if update else []

class AgentInput(TypedDict):
    messages: list[BaseMessage]

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    areas: list[AreaInfo]
    classifier_prompt: str
    agent_prompt: str
    selected_areas: list[AreaInfo]
    area_answers: Annotated[list[AreaAnswer], merge_answers]
    outcome: Outcome | None
    reply: str | None

class AreaTask(TypedDict):
    area: AreaInfo
    question: str
    history: list[BaseMessage]

AgentGraph = CompiledStateGraph[AgentState, AgentContext, AgentInput, AgentState]

# Tipos propios que viajan en el estado: LangGraph exige registrarlos para deserializarlos del checkpointer.
CHECKPOINT_TYPES = [
    ("src.agents.llm", "AreaInfo"),
    ("src.agents.llm", "AreaAnswer"),
    ("src.models.business_area", "AreaScope"),
]

def checkpoint_serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)

def build_graph(scope: AreaScope, checkpointer: BaseCheckpointSaver | None = None) -> AgentGraph:
    async def load_context(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
        catalog = await runtime.context.load_catalog(scope)
        return {
            "areas": catalog.areas,
            "classifier_prompt": catalog.classifier_prompt,
            "agent_prompt": catalog.agent_prompt,
            "selected_areas": [],
            "area_answers": [],
            "outcome": None,
            "reply": None,
        }

    async def classify(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
        *history, question = state["messages"]
        classification = await runtime.context.llm.classify(
            state["classifier_prompt"], question.text, state["areas"], history)
        if classification.wants_human:
            return {"outcome": "wants_human"}
        selected = [area for area in state["areas"] if area.id in classification.area_ids]
        own = [area for area in selected if area.scope == scope]
        if own and len(own) < len(selected):
            return {"outcome": "mixed_scope"}
        if not own:
            return {"outcome": "no_answer"}
        return {"selected_areas": own}

    def route(state: AgentState) -> list[Send] | str:
        if state["outcome"] is not None:
            return END
        *history, question = state["messages"]
        return [Send("answer_area", AreaTask(area=area, question=question.text, history=history))
                for area in state["selected_areas"]]

    async def answer_area(state: AreaTask, runtime: Runtime[AgentContext]) -> dict:
        area = state["area"]
        # Sin prompt o sin FAQ sobre el umbral el área no responde y no se llama al LLM: nunca inventa.
        if not area.system_prompt:
            return {"area_answers": [AreaAnswer(area.id, area.name, None)]}
        await runtime.context.retriever.refresh_stale_embeddings([area.id])
        faqs = await runtime.context.retriever.search(area.id, state["question"])
        if not faqs:
            return {"area_answers": [AreaAnswer(area.id, area.name, None)]}
        answer = await runtime.context.llm.answer(area, state["question"], faqs, state["history"])
        return {"area_answers": [answer]}

    async def combine(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
        answers = state["area_answers"]
        answered = [answer for answer in answers if answer.text is not None]
        if not answered:
            return {"outcome": "no_answer"}
        if len(answers) == 1:
            reply = answered[0].text
        else:
            reply = await runtime.context.llm.combine(state["agent_prompt"], state["messages"][-1].text, answers)
        outcome = "answered" if len(answered) == len(answers) else "partial"
        return {"outcome": outcome, "reply": reply, "messages": [AIMessage(reply)]}

    builder = StateGraph(AgentState, context_schema=AgentContext, input_schema=AgentInput)
    builder.add_node("load_context", load_context)
    builder.add_node("classify", classify)
    builder.add_node("answer_area", answer_area)
    builder.add_node("combine", combine)
    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "classify")
    builder.add_conditional_edges("classify", route, ["answer_area", END])
    builder.add_edge("answer_area", "combine")
    builder.add_edge("combine", END)
    return builder.compile(checkpointer=checkpointer)

async def run_agent(graph: AgentGraph, question: str, context: AgentContext, thread_id: str | None = None) -> AgentResult:
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}} if thread_id else {}
    state = await graph.ainvoke({"messages": [HumanMessage(question)]}, config, context=context)
    return AgentResult(state["outcome"], state["reply"], state["selected_areas"])

async def load_catalog(session: AsyncSession, scope: AreaScope) -> Catalog:
    areas = [*await get_areas(session, AreaScope.internal), *await get_areas(session, AreaScope.external)]
    classifier_prompt = await get_agent_prompt(session, "classifier")
    agent_prompt = await get_agent_prompt(session, f"{scope}_agent")
    if classifier_prompt is None or agent_prompt is None:
        logger.warning("Falta el prompt del clasificador o del agente %s en agent_prompt", scope)
    return Catalog(
        [AreaInfo(area.id, area.name, area.description, area.scope, area.system_prompt, area.owner_email) for area in areas],
        classifier_prompt or "",
        agent_prompt or "",
    )
