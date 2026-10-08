"""Baterías de comportamiento de asistente contra la BD y el modelo reales: clasificación de mensajes y elección de opciones.

Se ejecuta dentro del pod (o en local con la BD cargada); los avisos a las áreas solo se registran, no se envían.
Uso: uv run python -m src.cli.behavior_check --scope external
     uv run python -m src.cli.behavior_check --scope external --faqs 11,12 --procedure 7 --paraphrase "texto"
"""
import argparse
import asyncio
import dataclasses
import logging
import sys
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select
from src.agents.behavior import Clarification, ClarifyOption, requester_key
from src.agents.graph import AgentContext, AgentGraph, build_graph, checkpoint_serializer
from src.database.session import SessionLocal, engine
from src.models.business_area import AreaScope
from src.models.faq import Faq
from src.models.faq_category import FaqCategory
from src.models.procedure import Procedure
from src.services.area_notifier import Requester
from src.services.chat_orchestrator import build_agent_context

logger = logging.getLogger(__name__)

BOTH = (AreaScope.internal, AreaScope.external)
WEB = (AreaScope.external,)
FIXED = ("greeting", "closing", "off_topic")
# Identidad de prueba para el canal interno: los avisos a las áreas no se envían.
CHECK_REQUESTER = Requester("behavior_check", "behavior_check@local", "google_chat")

@dataclass(frozen=True)
class Case:
    message: str
    expected: str | frozenset[int]  # clase esperada, o las opciones que debe atender
    scopes: tuple[AreaScope, ...] = BOTH

@dataclass(frozen=True)
class CaseResult:
    case: Case
    observed: str | frozenset[int]
    ok: bool

# Batería de clasificación de la spec 002 (criterios de finalización); "other" es cualquier flujo que no sea un mensaje fijo.
CLASSIFICATION = [
    Case("hola", "greeting"),
    Case("buenas tardes", "greeting"),
    Case("hola, ¿cómo estás?", "greeting"),
    Case("👋", "greeting"),
    Case("hi", "greeting"),
    Case("gracias", "closing"),
    Case("ok", "closing"),
    Case("👍", "closing"),
    Case("hola, gracias", "closing"),
    Case("chao, que estés bien", "closing"),
    Case("hola, ¿cómo pago mi cuota?", "other", WEB),
    Case("necesito ayuda", "other"),
    Case("?", "other"),
    Case("dame una receta de pan", "off_topic"),
    Case("¿quién ganó el partido ayer?", "off_topic"),
    Case("¿cuántos días de vacaciones me quedan?", "off_topic", WEB),
]

def choice_cases(options: list[ClarifyOption], paraphrase: str) -> list[Case]:
    # Batería de elección de la spec 002 sobre una pregunta con 3 opciones (dos FAQ y un procedimiento).
    words = options[1].label.split()
    # Algo más de la mitad del texto, sin llegar al texto completo.
    partial = " ".join(words[: max(1, min(len(words) - 1, max(3, (len(words) + 1) // 2)))])
    two, both = frozenset({2}), frozenset({1, 2})
    return [
        Case("2", two), Case("la segunda", two), Case(partial, two), Case(paraphrase, two),
        Case("hola, la 2", two), Case("la 2, gracias", two), Case("la 1 y la 2", both),
        Case("4", "no_answer"), Case("ninguna", "no_answer"), Case("gracias", "closing"),
    ]

def thread_config() -> RunnableConfig:
    # Un hilo nuevo por caso: un mensaje no condiciona al siguiente.
    return {"configurable": {"thread_id": f"behavior-check-{uuid.uuid4()}"}}

def graph_classifier(graph: AgentGraph, context: AgentContext) -> Callable[[str], Awaitable[str]]:
    async def classify(message: str) -> str:
        state = await graph.ainvoke({"messages": [HumanMessage(message)]}, thread_config(), context=context)
        return state["outcome"] if state["outcome"] in FIXED else "other"
    return classify

def graph_chooser(graph: AgentGraph, context: AgentContext,
                  options: list[ClarifyOption]) -> Callable[[str], Awaitable[str | frozenset[int]]]:
    numbers = {(option.kind, option.item_id): option.number for option in options}

    async def choose(message: str) -> str | frozenset[int]:
        config = thread_config()
        pending = {requester_key(context.requester): Clarification("options", options)}
        # Como si la pregunta con opciones ya se hubiera enviado: el hilo queda cerrado y el mensaje entra como nuevo.
        await graph.aupdate_state(config, {"clarifications": pending}, as_node="finalize")
        state = await graph.ainvoke({"messages": [HumanMessage(message)]}, config, context=context)
        attended = frozenset(
            numbers[(kind, item_id)]
            for task in state.get("area_tasks") or []
            for kind, ids in (("faq", task["granted_faq_ids"]), ("procedure", task["granted_procedure_ids"]))
            for item_id in ids)
        return attended or state["outcome"]
    return choose

async def run_classification(classify: Callable[[str], Awaitable[str]], scope: AreaScope) -> list[CaseResult]:
    results = []
    for case in (case for case in CLASSIFICATION if scope in case.scopes):
        observed = await classify(case.message)
        results.append(CaseResult(case, observed, observed == case.expected))
    return results

async def run_choices(choose: Callable[[str], Awaitable[str | frozenset[int]]], cases: list[Case]) -> list[CaseResult]:
    results = []
    for case in cases:
        observed = await choose(case.message)
        results.append(CaseResult(case, observed, observed == case.expected))
    return results

class LoggingNotifier:
    async def notify(self, space: str, text: str) -> None:
        logger.info("Aviso no enviado al space %s (behavior_check)", space)

async def load_options(faq_ids: list[int], procedure_id: int) -> list[ClarifyOption]:
    async with SessionLocal() as session:
        faqs = {row.id: row for row in await session.execute(
            select(Faq.id, Faq.question, FaqCategory.area_id).join(FaqCategory, Faq.category_id == FaqCategory.id)
            .where(Faq.id.in_(faq_ids)))}
        procedure = (await session.execute(
            select(Procedure.id, Procedure.name, Procedure.area_id).where(Procedure.id == procedure_id))).one()
    options = [ClarifyOption(number, "faq", faq_id, faqs[faq_id].area_id, faqs[faq_id].question)
               for number, faq_id in enumerate(faq_ids, start=1)]
    return [*options, ClarifyOption(len(options) + 1, "procedure", procedure.id, procedure.area_id, procedure.name)]

def describe(observed: str | frozenset[int]) -> str:
    return f"opciones {sorted(observed)}" if isinstance(observed, frozenset) else observed

def report(title: str, results: list[CaseResult]) -> int:
    print(f"\n{title}")
    for result in results:
        status = "PASA " if result.ok else "FALLA"
        print(f"{status} | «{result.case.message}» → esperado {describe(result.case.expected)}, obtenido {describe(result.observed)}")
    passed = sum(1 for result in results if result.ok)
    print(f"{passed}/{len(results)} aciertos")
    return len(results) - passed

async def check(scope: AreaScope, faq_ids: list[int], procedure_id: int | None, paraphrase: str | None) -> int:
    graph = build_graph(scope, InMemorySaver(serde=checkpoint_serializer()))
    async with SessionLocal() as session:
        requester = CHECK_REQUESTER if scope == AreaScope.internal else None
        context = dataclasses.replace(await build_agent_context(session, requester), notifier=LoggingNotifier())
    failures = report("Clasificación", await run_classification(graph_classifier(graph, context), scope))
    if faq_ids and procedure_id is not None and paraphrase:
        options = await load_options(faq_ids, procedure_id)
        failures += report("Elección", await run_choices(graph_chooser(graph, context, options), choice_cases(options, paraphrase)))
    await engine.dispose()
    return 1 if failures else 0

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ejecuta las baterías de clasificación y de elección de la spec 002.")
    parser.add_argument("--scope", choices=[scope.value for scope in AreaScope], default=AreaScope.external.value)
    parser.add_argument("--faqs", default="", help="Ids de las dos FAQ de la pregunta con opciones, separados por coma")
    parser.add_argument("--procedure", type=int, help="Id del procedimiento de la pregunta con opciones")
    parser.add_argument("--paraphrase", help="Paráfrasis de la segunda opción")
    args = parser.parse_args(argv)
    faq_ids = [int(value) for value in args.faqs.split(",") if value.strip()]
    sys.exit(asyncio.run(check(AreaScope(args.scope), faq_ids, args.procedure, args.paraphrase)))

if __name__ == "__main__":
    main()
