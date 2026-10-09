import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from src.agents.llm import ANSWER_TOOL, CoordinatorModel, Embedder, RoutingDecision, SubAgentModel
from src.agents.tools import AreaTool


class PropertySession:
    """Sesión falsa sobre un dict: cuenta las consultas y lee el dict en cada una, como la tabla sin caché."""

    def __init__(self, values: dict[str, str], down: bool = False):
        self.values = values
        self.down = down
        self.queries = 0

    def _query(self) -> None:
        self.queries += 1
        if self.down:
            raise ConnectionRefusedError()

    async def scalar(self, statement: Any) -> str | None:
        self._query()
        key = next(iter(statement.compile().params.values()))
        return self.values.get(key)

    async def execute(self, statement: Any) -> list[SimpleNamespace]:
        self._query()
        return [SimpleNamespace(key=key, value=value) for key, value in self.values.items()]


def answer(found: bool, content: str = "") -> AIMessage:
    """Lo que devuelve un sub-agente al terminar: la llamada a `responder`."""
    return tool_call(ANSWER_TOOL, {"encontrado": found, "contenido": content}, "answer")


def tool_call(name: str, args: dict[str, Any], call_id: str = "call-1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


class FakeCoordinatorModel(CoordinatorModel):
    def __init__(self, decision: RoutingDecision | None = None, reply: str = "Respuesta final",
                 error: Exception | None = None, delay: float = 0.0):
        self.decision = decision or RoutingDecision("direct", reply="¡Hola!")
        self.reply = reply
        self.error = error
        self.delay = delay
        self.route_calls: list[list[BaseMessage]] = []
        self.synthesize_calls: list[list[BaseMessage]] = []

    async def route(self, messages: list[BaseMessage]) -> RoutingDecision:
        self.route_calls.append(messages)
        await self._wait_or_fail()
        return self.decision

    async def synthesize(self, messages: list[BaseMessage]) -> str:
        self.synthesize_calls.append(messages)
        await self._wait_or_fail()
        return self.reply

    async def _wait_or_fail(self) -> None:
        await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error


@dataclass
class SubAgentCall:
    messages: list[BaseMessage]
    tools: list[str]
    answer_only: bool


class FakeSubAgentModel(SubAgentModel):
    """Guion por subtarea: la clave es la consulta del HumanMessage; cada llamada consume el siguiente paso
    (el último se repite). Un paso que es una excepción se lanza."""

    def __init__(self, scripts: dict[str, list[AIMessage | Exception]] | None = None,
                 default: AIMessage | None = None, delay: float = 0.0):
        self.scripts = {query: list(steps) for query, steps in (scripts or {}).items()}
        self.default = default or answer(True, "Contenido del área")
        self.delay = delay
        self.calls: list[SubAgentCall] = []

    async def step(self, messages: list[BaseMessage], tools: Sequence[AreaTool], answer_only: bool) -> AIMessage:
        self.calls.append(SubAgentCall(messages, [tool.name for tool in tools], answer_only))
        await asyncio.sleep(self.delay)
        query = next((str(m.content) for m in messages if isinstance(m, HumanMessage)), "")
        steps = self.scripts.get(query)
        result = (steps.pop(0) if len(steps) > 1 else steps[0]) if steps else self.default
        if isinstance(result, Exception):
            raise result
        return result


class FakeEmbedder(Embedder):
    def __init__(self):
        self.batches: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(texts)
        return [[float(len(text)), 1.0, 0.0] for text in texts]
