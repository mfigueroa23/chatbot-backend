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
from src.agents.strategies import Notifier
from src.agents.sub_agent import run_sub_agent
from src.agents.tools import AreaToolbox
from src.services.area_notifier import Requester
from src.models.business_area import AreaScope
from src.services.business_data import get_agent_prompt, get_areas

logger = logging.getLogger(__name__)

Outcome = Literal["answered", "partial", "no_answer", "mixed_scope", "wants_human", "notification_failed"]

@dataclass(frozen=True)
class Catalog:
    areas: list[AreaInfo]  # de ambos ámbitos: el clasificador los necesita para detectar las preguntas mixtas
    classifier_prompt: str
    agent_prompt: str
    area_rules: str  # reglas comunes de todos los sub-agentes

@dataclass(frozen=True)
class AgentContext:
    """Dependencias de cada mensaje: el grafo se compila una vez y la configuración puede cambiar en la BD."""
    llm: AgentLLM
    retriever: Retriever
    load_catalog: Callable[[AreaScope], Awaitable[Catalog]]
    notifier: Notifier
    requester: Requester | None  # None en el canal web: el cliente es anónimo y da sus datos en el procedimiento
    max_steps: int = 4
    max_attempts: int = 3

@dataclass(frozen=True)
class AgentResult:
    outcome: Outcome
    reply: str | None
    areas: list[AreaInfo]  # áreas del ámbito a las que correspondía la pregunta

def merge_answers(current: list[AreaAnswer], update: list[AreaAnswer]) -> list[AreaAnswer]:
    # Una lista vacía reinicia las respuestas al empezar cada mensaje; el fan-out las va acumulando.
    return current + update if update else []

def merge_attempts(current: dict[int, int], update: dict[int, int]) -> dict[int, int]:
    # Las áreas corren en paralelo y cada una devuelve los contadores de sus procedimientos.
    return {**current, **update}

class AgentInput(TypedDict):
    messages: list[BaseMessage]

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    areas: list[AreaInfo]
    classifier_prompt: str
    agent_prompt: str
    area_rules: str
    selected_areas: list[AreaInfo]
    area_answers: Annotated[list[AreaAnswer], merge_answers]
    # Intentos fallidos por procedimiento; persiste entre mensajes del mismo hilo con el checkpointer.
    procedure_attempts: Annotated[dict[int, int], merge_attempts]
    outcome: Outcome | None
    reply: str | None

def text_of(message: BaseMessage) -> str:
    # message.text es una subclase de str que el cliente de Gemini serializa mal (500 en los embeddings).
    return str(message.text)

class AreaTask(TypedDict):
    area: AreaInfo
    rules: str
    question: str
    history: list[BaseMessage]
    attempts: dict[int, int]

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
            "area_rules": catalog.area_rules,
            "selected_areas": [],
            "area_answers": [],
            "procedure_attempts": {},
            "outcome": None,
            "reply": None,
        }

    async def classify(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
        *history, question = state["messages"]
        classification = await runtime.context.llm.classify(
            state["classifier_prompt"], text_of(question), state["areas"], history)
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
        return [Send("answer_area", AreaTask(area=area, rules=state["area_rules"], question=text_of(question), history=history,
                                             attempts=state["procedure_attempts"]))
                for area in state["selected_areas"]]

    async def answer_area(state: AreaTask, runtime: Runtime[AgentContext]) -> dict:
        area, context = state["area"], runtime.context
        toolbox = AreaToolbox(area, context.retriever, context.notifier, context.requester, state["question"],
                              state["attempts"], context.max_attempts)
        if area.system_prompt:
            await context.retriever.refresh_stale_embeddings([area.id])
        result = await run_sub_agent(context.llm, area, state["rules"], state["question"], state["history"], toolbox,
                                     context.max_steps)
        outcome = result.kind if result.kind in ("wants_human", "notification_failed") else None
        text = result.text if result.kind == "answered" else None
        return {"area_answers": [AreaAnswer(area.id, area.name, text, outcome)], "procedure_attempts": result.attempts}

    async def combine(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
        answers = state["area_answers"]
        # No poder avisar al área o derivar a un ejecutivo cambian el flujo del canal: tienen prioridad sobre el texto.
        for special in ("notification_failed", "wants_human"):
            if any(answer.outcome == special for answer in answers):
                return {"outcome": special}
        answered = [answer for answer in answers if answer.text is not None]
        if not answered:
            return {"outcome": "no_answer"}
        if len(answers) == 1:
            reply = answered[0].text
        else:
            reply = await runtime.context.llm.combine(state["agent_prompt"], text_of(state["messages"][-1]), answers)
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
    prompts = {key: await get_agent_prompt(session, key) for key in ("classifier", f"{scope}_agent", "area_rules")}
    missing = [key for key, value in prompts.items() if value is None]
    if missing:
        logger.warning("Faltan prompts en agent_prompt: %s", ", ".join(missing))
    return Catalog(
        [AreaInfo(area.id, area.name, area.description, area.scope, area.system_prompt, area.chat_space) for area in areas],
        prompts["classifier"] or "",
        prompts[f"{scope}_agent"] or "",
        prompts["area_rules"] or "",
    )
