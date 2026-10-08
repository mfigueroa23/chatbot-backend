"""Agente de ámbito (interno o externo): decide a qué áreas va una consulta y reúne lo que generan sus agentes.

No habla con el usuario: lo que devuelve es información para el coordinador.
"""
import asyncio
from dataclasses import dataclass, field
from langchain_core.messages import BaseMessage, HumanMessage
from src.agents.llm import (
    AgentLLM, AreaInfo, CallBudget, ProcedureHit, build_area_messages, build_scope_messages, describe_topics)
from src.agents.retriever import Retriever, ScopeSignals
from src.agents.strategies import Notifier
from src.agents.sub_agent import AreaAnswer, run_sub_agent
from src.agents.tools import AreaToolbox
from src.models.business_area import AreaScope
from src.services.area_notifier import Requester
from src.services.business_data import AreaTopics
from src.services.procedures import web_contact_fields

@dataclass(frozen=True)
class ScopeRequest:
    scope: AreaScope
    areas: list[AreaInfo]  # solo las del ámbito: el agente externo nunca recibe áreas internas
    topics: dict[int, AreaTopics]
    prompt: str
    rules: str  # reglas comunes de los agentes de área
    question: str
    history: list[BaseMessage]
    pending: ProcedureHit | None
    attempts: dict[int, int]
    requester: Requester | None
    notifier: Notifier
    history_messages: int = 20
    max_attempts: int = 3
    max_steps: int = 4

@dataclass(frozen=True)
class ScopeReport:
    answers: list[AreaAnswer]
    catalog: str | None = None  # temas y trámites del ámbito, cuando el usuario pregunta qué puede consultar
    attempts: dict[int, int] = field(default_factory=dict)

def previous_question(history: list[BaseMessage]) -> str | None:
    return next((str(message.text) for message in reversed(history) if isinstance(message, HumanMessage)), None)

def catalog_text(request: ScopeRequest) -> str:
    return "\n".join(describe_topics(area, request.topics.get(area.id), with_id=False) for area in request.areas)

async def run_scope_agent(llm: AgentLLM, retriever: Retriever, request: ScopeRequest, budget: CallBudget) -> ScopeReport:
    # Un área sin prompt no puede responder: no se le deriva nada.
    areas = {area.id: area for area in request.areas if area.system_prompt}
    previous = previous_question(request.history)
    query = f"{previous}\n{request.question}" if previous else request.question

    async def scope_signals() -> ScopeSignals:
        await retriever.refresh_stale_embeddings([area.id for area in request.areas])
        return await retriever.scope_signals(request.scope, query)

    budget.spend()
    # La decisión y el embedding con las señales del ámbito corren a la vez.
    decision, signals = await asyncio.gather(
        llm.decide_scope(build_scope_messages(
            request.prompt, request.areas, [], False, request.pending, request.history, request.question,
            request.history_messages, topics=request.topics)),
        scope_signals(),
    )
    if request.pending is not None and request.pending.area_id in areas:
        # Un procedimiento en curso sigue en su área aunque la decisión elija otra.
        selected = [areas[request.pending.area_id]]
    elif decision.catalogo:
        return ScopeReport([], catalog_text(request), dict(request.attempts))
    else:
        chosen = [areas[area_id] for area_id in dict.fromkeys(decision.area_ids) if area_id in areas]
        # Si no elige áreas válidas pero hay FAQ o procedimientos sobre el umbral, se deriva en sus áreas.
        selected = chosen or [areas[area_id] for area_id in signals.own_area_ids if area_id in areas]
    question = decision.consulta or request.question

    async def ask_area(area: AreaInfo) -> AreaAnswer:
        pending = request.pending if request.pending is not None and request.pending.area_id == area.id else None
        knowledge = await retriever.search_area(area.id, signals.embedding)
        toolbox = AreaToolbox(area, retriever, request.notifier, request.requester, request.question,
                              list(knowledge.faqs), list(knowledge.procedures), pending, request.attempts,
                              request.max_attempts)
        extra_fields = web_contact_fields() if area.scope == AreaScope.external else []
        messages = build_area_messages(area, request.rules, toolbox.faqs, toolbox.procedures, pending, request.history,
                                       question, request.history_messages, extra_fields)
        return await run_sub_agent(llm, toolbox, messages, request.max_steps, budget)

    answers = list(await asyncio.gather(*(ask_area(area) for area in selected)))
    attempts = dict(request.attempts)
    for answer in answers:
        attempts.update(answer.attempts)
    return ScopeReport(answers, None, attempts)
