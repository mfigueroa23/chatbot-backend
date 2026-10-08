import asyncio
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
from langgraph.types import Send
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.audit import GENERIC_REFUSAL, INTERNAL_NAMES, find_leaks, personal_data_leaks, strip_citations
from src.agents.behavior import (
    FREE_ANSWER_FALLBACK, PROCEDURE_EXHAUSTED, Candidate, Clarification, areas_question, build_options, can_clarify, chosen,
    combine, ensure_areas, fixed_text, options_text, other_procedures_text, requester_key)
from src.agents.llm import (
    AgentLLM, AreaInfo, ProcedureHit, build_area_messages, build_converse_messages, build_coordinator_messages)
from src.agents.retriever import Retriever, ScopeSignals
from src.agents.sub_agent import AreaAnswer, run_sub_agent
from src.agents.strategies import Notifier
from src.agents.tools import AreaToolbox
from src.models.business_area import AreaScope
from src.services.area_notifier import Requester
from src.services.business_data import get_agent_prompt, get_areas
from src.services.procedures import web_contact_fields

logger = logging.getLogger(__name__)

Outcome = Literal["answered", "no_answer", "mixed_scope", "wants_human", "notification_failed", "rejected", "greeting",
                  "closing", "off_topic", "offer_accepted", "offer_declined", "clarify", "about_assistant", "free_answer"]
# Mensajes fijos de cada canal: viven en agent_prompt con la key "<ámbito>_<tipo>".
FIXED_KINDS = ("greeting", "closing", "off_topic")

@dataclass(frozen=True)
class Catalog:
    areas: list[AreaInfo]  # solo las del ámbito del grafo: el contenido del otro ámbito nunca llega al modelo
    agent_prompt: str
    area_rules: str  # reglas comunes de todas las áreas
    fixed: dict[str, str | None] = field(default_factory=dict)  # texto de cada mensaje fijo; None si falta en la BD
    area_names: list[str] = field(default_factory=list)  # todas las áreas activas del ámbito, tengan prompt o no
    persona: str | None = None  # tono del asistente del canal; se lee en cada mensaje para aplicar los cambios de la BD

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

@dataclass(frozen=True)
class AgentResult:
    outcome: Outcome
    reply: str | None
    areas: list[AreaInfo]  # áreas en las que se apoyó la respuesta (o a las que correspondía la consulta)

class AgentInput(TypedDict):
    messages: list[BaseMessage]

def merge_answers(current: list[AreaAnswer], update: list[AreaAnswer]) -> list[AreaAnswer]:
    # Una lista vacía reinicia las respuestas al empezar cada mensaje; el fan-out las va acumulando.
    return current + update if update else []

def merge_attempts(current: dict[int, int], update: dict[int, int]) -> dict[int, int]:
    # Las áreas corren en paralelo y cada una devuelve los contadores de sus procedimientos.
    return {**current, **update}

class AreaTask(TypedDict):
    """Lo que recibe cada agente de área por Send: ids, no contenido; el agente busca lo suyo."""
    area: AreaInfo
    rules: str
    persona: str | None
    question: str
    history: list[BaseMessage]
    embedding: list[float]
    pending_procedure_id: int | None
    granted_faq_ids: list[int]
    granted_procedure_ids: list[int]
    attempts: dict[int, int]

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    # Persisten entre mensajes del mismo hilo.
    pending_area_id: int | None
    pending_procedure_id: int | None
    procedure_attempts: Annotated[dict[int, int], merge_attempts]
    clarifications: dict[str, Clarification]  # una aclaración pendiente por usuario (requester_key)
    # Por turno: coordinate los reinicia.
    turn_prompts: list[str]
    turn_agent_prompt: str
    turn_persona: str | None
    area_names: list[str]
    turn_candidates: list[Candidate]
    area_tasks: list[AreaTask]
    area_answers: Annotated[list[AreaAnswer], merge_answers]
    turn_note: str | None  # aviso de los procedimientos elegidos que no se iniciaron
    selected_areas: list[AreaInfo]
    outcome: Outcome | None
    reply: str | None

AgentGraph = CompiledStateGraph[AgentState, AgentContext, AgentInput, AgentState]

# Tipos propios que viajan en el estado: LangGraph exige registrarlos para deserializarlos del checkpointer.
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

def audited(text: str, prompts: list[str], used: list[AreaInfo], outcome: Outcome = "answered") -> dict:
    leaks = find_leaks(text, prompts, INTERNAL_NAMES)
    if leaks:
        # El texto filtrado no se envía ni queda en la memoria del hilo.
        logger.warning("Respuesta sustituida por el auditor: %s", ", ".join(leaks))
        return finish("rejected", memory=GENERIC_REFUSAL)
    return finish(outcome, text, used)

def free_text(text: str, prompts: list[str], fallback: str) -> dict:
    # Una fuga del prompt recibe la negativa genérica, como cualquier texto; sin texto o con datos personales se usa
    # un respaldo que no los tiene.
    found = personal_data_leaks(text)
    if found:
        logger.warning("Respuesta libre sustituida por datos personales: %s", ", ".join(found))
    if found or not text.strip():
        return finish("free_answer", fallback)
    return audited(text.strip(), prompts, [], "free_answer")

def drafted(text: str, prompts: list[str]) -> str | None:
    """Texto que redactó el modelo, si puede enviarse: None si viene vacío o el auditor encuentra una fuga."""
    if not text.strip():
        return None
    leaks = find_leaks(text, prompts, INTERNAL_NAMES)
    if leaks:
        logger.warning("Texto redactado sustituido por el auditor: %s", ", ".join(leaks))
        return None
    return text.strip()

def settle_clarification(state: AgentState, key: str, updates: dict) -> dict:
    # Cualquier respuesta que no sea una aclaración descarta la aclaración pendiente de ese usuario, y solo la suya.
    current = state.get("clarifications") or {}
    if updates.get("outcome") in (None, "clarify") or key not in current:
        return updates
    return updates | {"clarifications": {other: value for other, value in current.items() if other != key}}

def previous_question(history: list[BaseMessage]) -> str | None:
    # El mensaje anterior del usuario da contexto a las preguntas de seguimiento sin otra llamada al modelo.
    return next((text_of(message) for message in reversed(history) if isinstance(message, HumanMessage)), None)

def build_graph(scope: AreaScope, checkpointer: BaseCheckpointSaver | None = None) -> AgentGraph:
    # Ambos canales redactan sus textos; solo el interno responde libre: al cliente web nunca se le da información no
    # oficial, y sin respuesta sigue la pregunta de áreas y la oferta de ejecutivo.
    free_answers = scope == AreaScope.internal

    async def coordinate(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
        updates = await decide(state, runtime.context)
        return settle_clarification(state, requester_key(runtime.context.requester), updates)

    async def decide(state: AgentState, context: AgentContext) -> dict:
        *history, last = state["messages"]
        question = text_of(last)
        catalog = await context.load_catalog(scope)
        # Un área sin prompt no puede responder: el agente del canal no delega en ella.
        areas = {area.id: area for area in catalog.areas if area.system_prompt}
        pending = await pending_procedure(state, areas, context)
        clarification = (state.get("clarifications") or {}).get(requester_key(context.requester))
        options = clarification.options if clarification is not None else []
        previous = previous_question(history)
        query = f"{previous}\n{question}" if previous else question

        async def scope_signals() -> ScopeSignals:
            await context.retriever.refresh_stale_embeddings([area.id for area in catalog.areas])
            return await context.retriever.scope_signals(scope, query)

        # La llamada del agente del canal y el embedding con las señales del ámbito corren a la vez.
        decision, signals = await asyncio.gather(
            context.llm.coordinate(build_coordinator_messages(
                catalog.agent_prompt, list(areas.values()), options, context.offer_pending, pending, history, question,
                context.history_messages, catalog.persona)),
            scope_signals(),
        )
        # La persona también es un prompt: un texto que la copie se trata como fuga.
        prompts = [catalog.agent_prompt, catalog.area_rules, *(area.system_prompt or "" for area in catalog.areas),
                   *([catalog.persona] if catalog.persona else [])]
        turn = {
            "turn_prompts": prompts,
            "turn_agent_prompt": catalog.agent_prompt,
            "turn_persona": catalog.persona,
            "area_names": catalog.area_names,
            "turn_candidates": signals.candidates,
            "area_tasks": [],
            "area_answers": [],
            "turn_note": None,
            "selected_areas": [],
            "outcome": None,
            "reply": None,
        }
        own = [areas[area_id] for area_id in signals.own_area_ids if area_id in areas]
        if decision.kind == "manipulation":
            # La negativa redactada pasa por el auditor; vacía o con fuga, la genérica.
            refusal = drafted(decision.text, prompts)
            return turn | (finish("rejected", refusal) if refusal else finish("rejected", memory=GENERIC_REFUSAL))
        if decision.kind == "wants_human":
            return turn | finish("wants_human", areas=own)
        # La respuesta a la oferta de ejecutivo solo cuenta si hay una oferta pendiente.
        if context.offer_pending and decision.kind == "accept_offer":
            return turn | finish("offer_accepted")
        if context.offer_pending and decision.kind == "decline_offer":
            return turn | finish("offer_declined")
        if own and signals.other_scope_match:
            return turn | finish("mixed_scope")
        # Una pregunta sobre el asistente con una FAQ propia sobre el umbral la responde el área; sin texto sigue el
        # flujo normal, y un texto con fuga recibe la negativa genérica.
        if decision.kind == "about_assistant" and not own and decision.text.strip():
            about = drafted(decision.text, prompts)
            return turn | (finish("about_assistant", about) if about else finish("rejected", memory=GENERIC_REFUSAL))
        # Una FAQ o un procedimiento propio sobre el umbral demuestran que el mensaje no es ajeno al canal.
        fixed_kind = None
        if decision.kind in ("greeting", "closing") or (decision.kind == "off_topic" and not own):
            fixed_kind = decision.kind
        if fixed_kind is None and signals.other_scope_match and not own:
            fixed_kind = "off_topic"
        if fixed_kind is not None:
            # El saludo y el fuera de tema dicen con qué puede ayudar el asistente; el cierre no.
            names = [] if fixed_kind == "closing" else catalog.area_names
            # El texto redactado solo vale para lo que clasificó el agente del canal; vacío o con fuga, el texto fijo.
            text = drafted(decision.text, prompts) if decision.kind == fixed_kind else None
            if text:
                return turn | finish(fixed_kind, ensure_areas(text, names))
            template = catalog.fixed.get(fixed_kind)
            if template:
                return turn | finish(fixed_kind, fixed_text(template, names))
            # Sin texto en la BD el mensaje sigue el flujo normal: procedimiento, FAQ, aclaración o sin respuesta.
            logger.error("Falta el texto fijo %s_%s en agent_prompt", scope, fixed_kind)

        def task(area: AreaInfo, pending_id: int | None = None) -> AreaTask:
            return AreaTask(area=area, rules=catalog.area_rules, persona=catalog.persona, question=question, history=history,
                            embedding=signals.embedding, pending_procedure_id=pending_id, granted_faq_ids=[],
                            granted_procedure_ids=[], attempts=state.get("procedure_attempts") or {})

        if pending is not None:
            # Un procedimiento en curso sigue en su área aunque el agente del canal elija otra.
            return turn | {"area_tasks": [task(areas[pending.area_id], pending.id)]}
        if decision.kind == "choice" and clarification is not None and clarification.kind == "options":
            # Solo cuenta la elección de quien recibió las opciones: la aclaración se busca por su requester_key.
            picked = chosen(clarification.options, decision.chosen_options)
            tasks: dict[int, AreaTask] = {}
            for option in [*picked.faqs, *([picked.procedure] if picked.procedure else [])]:
                if option.area_id not in areas:
                    continue
                target = tasks.setdefault(option.area_id, task(areas[option.area_id]))
                (target["granted_faq_ids"] if option.kind == "faq" else target["granted_procedure_ids"]).append(option.item_id)
            note = other_procedures_text(picked.other_procedures) if picked.other_procedures else None
            # Una elección que no corresponde a ninguna opción válida no se delega: va al flujo de sin respuesta.
            return turn | {"area_tasks": list(tasks.values()), "turn_note": note}
        selected = []
        if decision.kind == "delegate":
            selected = [areas[area_id] for area_id in dict.fromkeys(decision.area_ids) if area_id in areas]
        # Si el agente del canal no elige áreas válidas, o no delega pese a haber FAQ o procedimientos sobre el umbral
        # de respuesta, se delega en las áreas con coincidencias: el agente del área decide si responde.
        return turn | {"area_tasks": [task(area) for area in selected or own]}

    def route(state: AgentState) -> list[Send] | str:
        if state.get("outcome") is not None:
            return END
        tasks = state.get("area_tasks") or []
        if not tasks:
            return "finalize"
        return [Send("area_agent", task) for task in tasks]

    async def area_agent(state: AreaTask, runtime: Runtime[AgentContext]) -> dict:
        context, area = runtime.context, state["area"]
        pending = None
        if state["pending_procedure_id"] is not None:
            pending = await context.retriever.get_procedure(area.id, state["pending_procedure_id"])
        knowledge = await context.retriever.search_area(area.id, state["embedding"])
        faqs, procedures = list(knowledge.faqs), list(knowledge.procedures)
        for faq_id in state["granted_faq_ids"]:
            granted = await context.retriever.get_faq(area.id, faq_id)
            if granted is not None and all(faq.id != granted.id for faq in faqs):
                faqs.append(granted)
        for procedure_id in state["granted_procedure_ids"]:
            granted_procedure = await context.retriever.get_procedure(area.id, procedure_id)
            if granted_procedure is not None and all(p.id != granted_procedure.id for p in procedures):
                procedures.append(granted_procedure)
        extra_fields = web_contact_fields() if area.scope == AreaScope.external else []
        toolbox = AreaToolbox(area, context.retriever, context.notifier, context.requester, state["question"], faqs,
                              procedures, pending, state["attempts"], context.max_attempts)
        messages = build_area_messages(area, state["rules"], faqs, procedures, pending, state["history"], state["question"],
                                       context.history_messages, extra_fields, state["persona"])
        answer = await run_sub_agent(context.llm, toolbox, messages, context.max_steps)
        return {"area_answers": [answer], "procedure_attempts": answer.attempts}

    async def finalize(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
        key = requester_key(runtime.context.requester)
        return settle_clarification(state, key, await close(state, key, runtime.context))

    async def close(state: AgentState, key: str, context: AgentContext) -> dict:
        answers = state.get("area_answers") or []
        cleared = {"pending_area_id": None, "pending_procedure_id": None}
        # No poder avisar al área cambia el flujo del canal: tiene prioridad sobre cualquier texto.
        failed = next((answer for answer in answers if answer.kind == "notification_failed"), None)
        if failed is not None:
            return finish("notification_failed", areas=[failed.area]) | cleared
        gave_up = next((answer for answer in answers if answer.kind == "gave_up"), None)
        if gave_up is not None and gave_up.procedure_id is not None:
            reset = cleared | {"procedure_attempts": {gave_up.procedure_id: 0}}
            if free_answers:
                # En el canal interno no se avisa al área sin que el colaborador lo pida: se le ofrece hacerlo.
                return await exhausted(state, gave_up, context) | reset
            # Tras los intentos permitidos se aplica el flujo de sin respuesta del canal.
            return finish("no_answer", areas=[gave_up.area]) | reset
        with_text = ("answered", "procedure_ask", "procedure_sent")
        reply = combine([(answer.area.name, strip_citations(answer.text) if answer.text and answer.kind in with_text else None)
                         for answer in answers])
        if reply is None:
            clarification = await clarify(state, key, context)
            if clarification is not None:
                return clarification
            if free_answers:
                # La conversación solo cuesta una llamada más cuando ninguna área respondió.
                text = await context.llm.converse(conversation(state, context, []))
                return free_text(text, state["turn_prompts"], FREE_ANSWER_FALLBACK)
            return finish("no_answer", areas=[answer.area for answer in answers])
        if state.get("turn_note"):
            reply = f"{reply}\n\n{state['turn_note']}"
        updates = audited(reply, state["turn_prompts"], [answer.area for answer in answers if answer.text])
        asked = next((answer for answer in answers if answer.kind == "procedure_ask"), None)
        if asked is not None and updates["outcome"] == "answered":
            return updates | {"pending_area_id": asked.area.id, "pending_procedure_id": asked.procedure_id}
        if any(answer.kind == "procedure_sent" for answer in answers):
            return updates | cleared
        return updates

    async def clarify(state: AgentState, key: str, context: AgentContext) -> dict | None:
        # Sin aclaraciones dentro de un procedimiento en curso: ahí manda el flujo del procedimiento.
        if state.get("pending_procedure_id") is not None:
            return None
        clarifications = state.get("clarifications") or {}
        pending = clarifications.get(key)
        options = build_options(state.get("turn_candidates") or [])
        if options and can_clarify(pending, "options"):
            # El modelo propone los temas con sus palabras; se guardan las mismas opciones numeradas, así la elección
            # se reconoce igual. Sin texto o con fuga, la plantilla.
            written = await context.llm.converse(conversation(state, context, [option.label for option in options]))
            text = drafted(written, state["turn_prompts"]) or options_text(options)
            clarification = Clarification("options", options)
        elif not options and not free_answers and can_clarify(pending, "areas"):
            clarification, text = Clarification("areas"), areas_question(state.get("area_names") or [])
        else:
            return None
        updates = audited(text, state["turn_prompts"], [])
        if updates["outcome"] != "answered":
            return updates
        return finish("clarify", text) | {"clarifications": {**clarifications, key: clarification}}

    async def exhausted(state: AgentState, gave_up: AreaAnswer, context: AgentContext) -> dict:
        procedure = None
        if gave_up.procedure_id is not None:
            procedure = await context.retriever.get_procedure(gave_up.area.id, gave_up.procedure_id)
        name = procedure.name if procedure is not None else gave_up.area.name
        text = await context.llm.converse(conversation(state, context, [], name))
        return free_text(text, state["turn_prompts"], PROCEDURE_EXHAUSTED.format(name=name))

    graph = StateGraph(AgentState, context_schema=AgentContext, input_schema=AgentInput)
    graph.add_node("coordinate", coordinate)
    graph.add_node("area_agent", area_agent)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "coordinate")
    graph.add_conditional_edges("coordinate", route, [END, "finalize", "area_agent"])
    graph.add_edge("area_agent", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)

def conversation(state: AgentState, context: AgentContext, topics: list[str],
                 exhausted_procedure: str | None = None) -> list[BaseMessage]:
    *history, last = state["messages"]
    return build_converse_messages(state.get("turn_persona"), state.get("turn_agent_prompt") or "",
                                   state.get("area_names") or [], topics, history, text_of(last), context.history_messages,
                                   exhausted_procedure)

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
    prompts = {key: await get_agent_prompt(session, key) for key in (f"{scope}_agent", "area_rules")}
    fixed = {kind: await get_agent_prompt(session, f"{scope}_{kind}") for kind in FIXED_KINDS}
    persona = await get_agent_prompt(session, f"{scope}_persona")
    missing = [key for key, value in prompts.items() if value is None]
    if missing:
        logger.warning("Faltan prompts en agent_prompt: %s", ", ".join(missing))
    return Catalog(
        [AreaInfo(area.id, area.name, area.description, area.scope, area.system_prompt, area.chat_space) for area in areas],
        prompts[f"{scope}_agent"] or "",
        prompts["area_rules"] or "",
        fixed,
        [area.name for area in areas],
        persona,
    )
