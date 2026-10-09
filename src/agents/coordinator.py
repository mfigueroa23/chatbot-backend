"""Coordinador del patrón (agente externo o interno): decide las subtareas y redacta la respuesta."""
import logging
from collections.abc import Sequence
from langchain_core.messages import BaseMessage
from src.agents.llm import AreaResult, Catalog, CoordinatorModel, RoutingDecision, Subtask
from src.agents.prompts import route_messages, synthesize_messages

logger = logging.getLogger(__name__)

def sanitize(decision: RoutingDecision, catalog: Catalog, max_areas: int) -> RoutingDecision:
    """Solo áreas del catálogo del canal, una subtarea por área y como máximo max_areas (D4: RF-3, RF-6, RF-40)."""
    if decision.kind == "direct" and decision.reply.strip():
        return RoutingDecision("direct", reply=decision.reply.strip())
    subtasks: list[Subtask] = []
    for subtask in decision.subtasks:
        if catalog.area(subtask.area_id) is None:
            logger.warning("Se descarta una subtarea para el área %s, que no está en el catálogo", subtask.area_id)
        elif subtask.query.strip() and subtask.area_id not in {kept.area_id for kept in subtasks}:
            subtasks.append(Subtask(subtask.area_id, subtask.query.strip()))
    if len(subtasks) > max_areas:
        logger.info("La consulta toca %s áreas; se consultan las primeras %s", len(subtasks), max_areas)
    # Sin subtareas válidas sigue como consulta a las áreas: synthesize dirá que no tiene esa información (RF-14).
    return RoutingDecision("areas", tuple(subtasks[:max_areas]))

async def route(model: CoordinatorModel, catalog: Catalog, history: Sequence[BaseMessage], question: str,
                max_areas: int, person: str | None = None) -> RoutingDecision:
    decision = await model.route(route_messages(catalog, history, question, person))
    return sanitize(decision, catalog, max_areas)

async def synthesize(model: CoordinatorModel, catalog: Catalog, history: Sequence[BaseMessage], question: str,
                     results: Sequence[AreaResult], person: str | None = None) -> str:
    return await model.synthesize(synthesize_messages(catalog, history, question, results, person))
