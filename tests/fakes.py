import asyncio
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from src.agents.llm import (ANSWER_TOOL, AreaInfo, Catalog, CoordinatorModel, EdrWriter, Embedder, FaqHit,
                            KnowledgeSource, RoutingDecision, SubAgentModel, Subtask, Transcriber)
from src.agents.tools.registry import AreaTool
from src.models.business_area import AreaScope
from src.services.assistant import AssistantDeps, FileReader, Models
from src.services.conversation import ConversationStore
from src.services.edr.store import EdrRecord, EdrRepository
from src.services.property import Properties
from src.utils.exceptions.database import DatabaseUnavailableError


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


def answer(found: bool, content: str = "", interpretations: list[str] | None = None) -> AIMessage:
    """Lo que devuelve un sub-agente al terminar: la llamada a `responder`."""
    return tool_call(ANSWER_TOOL, {"encontrado": found, "contenido": content,
                                   "interpretaciones": interpretations or []}, "answer")


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

    def __init__(self, scripts: Mapping[str, Sequence[AIMessage | Exception]] | None = None,
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


class FakeTranscriber(Transcriber):
    def __init__(self, text: str = "Texto transcrito", error: Exception | None = None):
        self.text = text
        self.error = error
        self.calls: list[str] = []

    async def transcribe(self, data: bytes, mime_type: str) -> str:
        self.calls.append(mime_type)
        if self.error is not None:
            raise self.error
        return self.text


class FakeEmbedder(Embedder):
    def __init__(self):
        self.batches: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(texts)
        return [[float(len(text)), 1.0, 0.0] for text in texts]


class FakeKnowledge(KnowledgeSource):
    def __init__(self, faqs: Mapping[int, list[FaqHit]] | None = None):
        self.faqs = dict(faqs or {})
        self.searches: list[tuple[list[Subtask], int]] = []
        self.area_searches: list[tuple[int, str, int]] = []

    async def search(self, subtasks: Sequence[Subtask], k: int) -> dict[int, list[FaqHit]]:
        self.searches.append((list(subtasks), k))
        return {subtask.area_id: self.faqs.get(subtask.area_id, [])[:k] for subtask in subtasks}

    async def search_area(self, area_id: int, query: str, k: int) -> list[FaqHit]:
        self.area_searches.append((area_id, query, k))
        return self.faqs.get(area_id, [])[:k]


class FakeConversationStore(ConversationStore):
    """En memoria: guarda (rol, texto) por conversación, como la tabla message."""

    def __init__(self, down: bool = False):
        self.down = down
        self.messages: dict[uuid.UUID, list[BaseMessage]] = {}
        self.keys: dict[str, uuid.UUID] = {}
        self.last_message_at: dict[uuid.UUID, datetime] = {}

    async def web_conversation(self, session_id: uuid.UUID | None, now: datetime) -> uuid.UUID:
        if self.down:
            raise DatabaseUnavailableError("conexión rechazada")
        if session_id is not None and session_id in self.messages:
            return session_id
        return self._create(now)

    async def chat_conversation(self, key: str, now: datetime) -> uuid.UUID:
        if self.down:
            raise DatabaseUnavailableError("conexión rechazada")
        if key not in self.keys:
            self.keys[key] = self._create(now)
        return self.keys[key]

    async def history(self, conversation_id: uuid.UUID, limit: int) -> list[BaseMessage]:
        return self.messages[conversation_id][-limit:] if limit > 0 else []

    async def append_turn(self, conversation_id: uuid.UUID, question: str, reply: str, now: datetime) -> None:
        self.messages[conversation_id] += [HumanMessage(question), AIMessage(reply)]
        self.last_message_at[conversation_id] = now

    async def delete_expired(self, cutoff: datetime) -> int:
        expired = [cid for cid, last in self.last_message_at.items() if last < cutoff]
        for cid in expired:
            del self.messages[cid], self.last_message_at[cid]
        return len(expired)

    def _create(self, now: datetime) -> uuid.UUID:
        conversation_id = uuid.uuid4()
        self.messages[conversation_id] = []
        self.last_message_at[conversation_id] = now
        return conversation_id


SAC = AreaInfo(1, "Servicio al Cliente", "Pagos", "Eres SAC.", ("Pagos",))
EXTERNAL = Catalog(AreaScope.external, "Coordinador externo.", "Reglas.", (SAC,))
INTERNAL = Catalog(AreaScope.internal, "Coordinador interno.", "Reglas.", ())
SECRET = "AIza-clave-secreta"
PROPERTIES = {"gemini_api_key": SECRET, "history_messages": "2", "response_timeout_seconds": "5"}


class AssistantHarness:
    """Arma AssistantDeps con dobles y deja a mano lo que cada test quiere cambiar o mirar."""

    def __init__(self, coordinator: FakeCoordinatorModel | None = None, properties: dict[str, str] | None = None,
                 db_down: bool = False, read_files: FileReader | None = None):
        self.read_files = read_files
        self.coordinator = coordinator or FakeCoordinatorModel(RoutingDecision("direct", reply="¡Hola!"))
        self.properties = dict(PROPERTIES if properties is None else properties)
        self.store = FakeConversationStore(down=db_down)
        self.catalogs = {AreaScope.external: EXTERNAL, AreaScope.internal: INTERNAL}
        self.prompts = {"internal_welcome": "¡Hola! Soy el asistente."}
        self.requested_scopes: list[AreaScope] = []

    def deps(self) -> AssistantDeps:
        async def properties() -> Properties:
            return Properties(dict(self.properties))

        async def catalog(scope: AreaScope) -> Catalog:
            self.requested_scopes.append(scope)
            return self.catalogs[scope]

        def models(properties: Properties) -> Models:
            properties.required("gemini_api_key")
            return Models(self.coordinator, FakeSubAgentModel(), FakeEmbedder(), FakeTranscriber())

        async def prompt(key: str) -> str | None:
            return self.prompts.get(key)

        return AssistantDeps(properties, self.store, catalog, models, lambda embedder: FakeKnowledge(), prompt,
                             read_files=self.read_files)


class FakeEdrRepository(EdrRepository):
    """En memoria: el EDR de cada conversación, su historial y los prompts."""

    def __init__(self, history: list[BaseMessage] | None = None, prompts: dict[str, str] | None = None):
        self.records: dict[uuid.UUID, list[EdrRecord]] = {}
        self.messages = list(history or [])
        self.replies: list[str] = []
        self.prompts = dict(prompts or {"edr_writer": "Eres el redactor de EDR."})

    async def latest(self, conversation_id: uuid.UUID) -> EdrRecord | None:
        records = self.records.get(conversation_id, [])
        return records[-1] if records else None

    async def save(self, conversation_id: uuid.UUID, record: EdrRecord) -> None:
        records = [kept for kept in self.records.get(conversation_id, []) if kept.drive_file_id != record.drive_file_id]
        self.records[conversation_id] = [*records, record]

    async def history(self, conversation_id: uuid.UUID, limit: int) -> list[BaseMessage]:
        return self.messages[-limit:]

    async def append_reply(self, conversation_id: uuid.UUID, reply: str, now: datetime) -> None:
        self.replies.append(reply)

    async def prompt(self, key: str) -> str | None:
        return self.prompts.get(key)


class FakeEdrWriter(EdrWriter):
    """Devuelve las respuestas en orden (la última se repite) y guarda los mensajes de cada llamada."""

    def __init__(self, *replies: str, delay: float = 0.0):
        self.replies = list(replies) or ['{"titulo": "EDR de prueba"}']
        self.delay = delay
        self.calls: list[list[BaseMessage]] = []

    async def write(self, messages: list[BaseMessage]) -> str:
        self.calls.append(messages)
        await asyncio.sleep(self.delay)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
