"""Batería de variedad de los saludos contra la BD y el modelo reales (spec 004, RNF-4).

Con el coordinador de la spec 004 no hay categorías que clasificar: el tono se acepta en la demo manual y esta batería
mide que los saludos de conversaciones nuevas no sean siempre idénticos. Se ejecuta dentro del pod (o en local con la BD
cargada); los avisos a las áreas solo se registran, no se envían.
Uso: uv run python -m src.cli.behavior_check --scope internal --variety 5
"""
import argparse
import asyncio
import dataclasses
import logging
import sys
import uuid
from collections.abc import Awaitable, Callable
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from src.agents.graph import AgentContext, AgentGraph, build_graph, checkpoint_serializer
from src.database.session import SessionLocal, engine
from src.models.business_area import AreaScope
from src.services.area_notifier import Requester
from src.services.chat_orchestrator import build_agent_context

logger = logging.getLogger(__name__)

# Identidad de prueba para el canal interno: los avisos a las áreas no se envían.
CHECK_REQUESTER = Requester("behavior_check", "behavior_check@local", "google_chat")

def thread_config() -> RunnableConfig:
    # Un hilo nuevo por saludo: un mensaje no condiciona al siguiente.
    return {"configurable": {"thread_id": f"behavior-check-{uuid.uuid4()}"}}

def graph_greeter(graph: AgentGraph, context: AgentContext) -> Callable[[str], Awaitable[str]]:
    async def greet(message: str) -> str:
        state = await graph.ainvoke({"messages": [HumanMessage(message)]}, thread_config(), context=context)
        return state["reply"] or ""
    return greet

def required_variety(count: int) -> int:
    # Al menos 3 textos distintos de cada 5 saludos, redondeando hacia arriba.
    return -(-3 * count // 5)

async def run_variety(greet: Callable[[str], Awaitable[str]], count: int) -> tuple[list[str], bool]:
    replies = [await greet("hola") for _ in range(count)]
    return replies, len(set(replies)) >= required_variety(count)

class LoggingNotifier:
    async def notify(self, space: str, text: str) -> None:
        logger.info("Aviso no enviado al space %s (behavior_check)", space)

def report_variety(replies: list[str], ok: bool) -> int:
    print("\nVariedad")
    for reply in replies:
        print(f"- {reply[:120]}")
    print(f"{'PASA ' if ok else 'FALLA'} | {len(set(replies))} textos distintos de {len(replies)} "
          f"(mínimo {required_variety(len(replies))})")
    return 0 if ok else 1

async def check(scope: AreaScope, variety: int) -> int:
    graph = build_graph(scope, InMemorySaver(serde=checkpoint_serializer()))
    async with SessionLocal() as session:
        requester = CHECK_REQUESTER if scope == AreaScope.internal else None
        context = dataclasses.replace(await build_agent_context(session, requester), notifier=LoggingNotifier())
    failures = report_variety(*await run_variety(graph_greeter(graph, context), variety))
    await engine.dispose()
    return 1 if failures else 0

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Mide la variedad de los saludos del coordinador (spec 004).")
    parser.add_argument("--scope", choices=[scope.value for scope in AreaScope], default=AreaScope.external.value)
    parser.add_argument("--variety", type=int, default=5, help="Saludos en hilos nuevos para medir la variedad de los textos")
    args = parser.parse_args(argv)
    sys.exit(asyncio.run(check(AreaScope(args.scope), args.variety)))

if __name__ == "__main__":
    main()
