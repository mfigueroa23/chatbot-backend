import uuid
from datetime import UTC, datetime, timedelta
from typing import cast
from langchain_core.messages import BaseMessage
from sqlalchemy.ext.asyncio import AsyncSession
import re
from src.agents.behavior import Candidate
from src.agents.llm import AgentReply, AgentStep, CoordinatorReply, FaqHit, FinalText, ToolCall, ToolCalls, ToolSpec
from src.agents.retriever import AreaKnowledge, Knowledge, ProcedureHit, ScopeSignals
from src.models.business_area import AreaScope
from src.models.executive import Executive
from src.models.executive_session import ExecutiveSession
from src.models.live_chat import LiveChat, LiveChatStatus
from src.models.web_session import WebPhase, WebSession
from src.services.realtime import ConnectionHub, Event
from src.utils.exceptions.notification import NotificationDeliveryError


class FakeClock:
    def __init__(self, now: datetime):
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


class PropertySession:
    def __init__(self, values: dict[str, str]):
        self.values = values

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def execute(self, statement):
        return []

    async def scalar(self, statement):
        # get_property filtra por una sola key: se toma del parámetro de la sentencia.
        (key,) = statement.compile().params.values()
        return self.values.get(key)

    async def commit(self):
        pass

    async def rollback(self):
        pass


def property_session(values: dict[str, str]) -> AsyncSession:
    return cast(AsyncSession, PropertySession(values))


AREA_HEADER = re.compile(r"### Área: (.+)")


class FakeAgentLLM:
    """Guioniza el modelo y cuenta sus llamadas.

    Las respuestas de la llamada única (AgentReply) también sirven para el grafo de agentes de área: el agente del
    canal delega (o marca manipulación o persona) y cada agente de área responde con el texto o inicia el procedimiento.
    `coordinator` y `steps` (por nombre de área) guionizan el grafo nuevo de forma explícita.
    """

    def __init__(self, *replies: AgentReply, coordinator: list[CoordinatorReply] | None = None,
                 steps: dict[str, list[AgentStep]] | None = None):
        self.replies = list(replies) or [AgentReply("no_answer", "")]
        self.coordinator = list(coordinator or [])
        self.steps = {area: list(script) for area, script in (steps or {}).items()}
        self.calls = 0
        self.coordinator_calls = 0
        self.step_calls = 0
        self.messages: list[list[BaseMessage]] = []
        self.coordinator_messages: list[list[BaseMessage]] = []
        self.step_messages: list[list[BaseMessage]] = []
        self.current: AgentReply | None = None

    async def respond(self, messages: list[BaseMessage]) -> AgentReply:
        self.calls += 1
        self.messages.append(list(messages))
        return self.next_reply()

    async def coordinate(self, messages: list[BaseMessage]) -> CoordinatorReply:
        self.coordinator_calls += 1
        self.coordinator_messages.append(list(messages))
        if self.coordinator:
            return self.coordinator.pop(0) if len(self.coordinator) > 1 else self.coordinator[0]
        self.current = self.next_reply()
        if self.current.kind in ("manipulation", "wants_human"):
            return CoordinatorReply(self.current.kind)
        # Sin áreas: el grafo delega en las áreas con coincidencias, como hacía la búsqueda de la llamada única.
        return CoordinatorReply("delegate")

    async def step(self, messages: list[BaseMessage], tools: list[ToolSpec]) -> AgentStep:
        self.step_calls += 1
        self.step_messages.append(list(messages))
        match = AREA_HEADER.search(str(messages[0].content)) if messages else None
        script = self.steps.get(match.group(1)) if match else None
        if script:
            return script.pop(0) if len(script) > 1 else script[0]
        reply = self.current or self.replies[0]
        if reply.kind == "procedure" and reply.procedure_id is not None:
            data = [{"campo": name, "valor": value} for name, value in reply.data.items()]
            call = ToolCall("call-1", "iniciar_procedimiento", {"procedimiento_id": reply.procedure_id, "datos": data})
            return ToolCalls([call], reply.text)
        return FinalText(reply.text if reply.kind == "answer" else "")

    def next_reply(self) -> AgentReply:
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


def answer(text: str, *faq_ids: int) -> AgentReply:
    return AgentReply("answer", text, list(faq_ids))


def procedure(procedure_id: int, text: str = "", **data: str) -> AgentReply:
    return AgentReply("procedure", text, procedure_id=procedure_id, data=data)


class FakeEmbedder:
    def __init__(self):
        self.queries: list[str] = []
        self.documents: list[str] = []

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [0.1] * 768

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.documents.extend(texts)
        return [[0.2] * 768 for _ in texts]


class FakeRetriever:
    def __init__(self, faqs: list[FaqHit] | None = None, procedures: list[ProcedureHit] | None = None,
                 other_scope_match: bool = False, stored: list[ProcedureHit] | None = None,
                 candidates: list[Candidate] | None = None, stored_faqs: list[FaqHit] | None = None):
        self.faqs = faqs or []
        self.procedures = procedures or []
        # Procedimientos y FAQ que existen en la BD aunque la búsqueda de este mensaje no los devuelva.
        self.stored = (stored or []) + self.procedures
        self.stored_faqs = (stored_faqs or []) + self.faqs
        self.other_scope_match = other_scope_match
        self.candidates = candidates or []
        self.searches: list[tuple[AreaScope, str]] = []
        self.area_searches: list[int] = []
        self.tool_searches: list[tuple[int, str]] = []
        self.refreshed_area_ids: list[int] = []

    async def scope_signals(self, scope: AreaScope, query: str) -> ScopeSignals:
        self.searches.append((scope, query))
        own = [item.area_id for item in [*self.faqs, *self.procedures]]
        return ScopeSignals([0.1] * 768, list(dict.fromkeys(own)), list(self.candidates), self.other_scope_match)

    async def search_area(self, area_id: int, embedding: list[float]) -> AreaKnowledge:
        self.area_searches.append(area_id)
        return AreaKnowledge([f for f in self.faqs if f.area_id == area_id],
                             [p for p in self.procedures if p.area_id == area_id])

    async def search_area_faqs(self, area_id: int, query: str) -> list[FaqHit]:
        self.tool_searches.append((area_id, query))
        return [f for f in self.faqs if f.area_id == area_id]

    async def search_area_procedures(self, area_id: int, query: str) -> list[ProcedureHit]:
        self.tool_searches.append((area_id, query))
        return [p for p in self.procedures if p.area_id == area_id]

    async def get_faq(self, area_id: int, faq_id: int) -> FaqHit | None:
        return next((f for f in self.stored_faqs if f.id == faq_id and f.area_id == area_id), None)

    async def search_scope(self, scope: AreaScope, query: str) -> Knowledge:
        self.searches.append((scope, query))
        return Knowledge(list(self.faqs), list(self.procedures), self.other_scope_match)

    async def get_procedure(self, area_id: int, procedure_id: int) -> ProcedureHit | None:
        return next((p for p in self.stored if p.id == procedure_id and p.area_id == area_id), None)

    async def refresh_stale_embeddings(self, area_ids: list[int]) -> None:
        self.refreshed_area_ids.extend(area_ids)


class FakeNotifier:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.sent: list[tuple[str, str]] = []

    async def notify(self, space: str, text: str) -> None:
        if self.fail:
            raise NotificationDeliveryError(space)
        self.sent.append((space, text))


class FakeExecutiveRepository:
    def __init__(self, executives: list[Executive] | None = None):
        self.executives = {executive.username.lower(): executive for executive in executives or []}
        self.sessions: dict[str, ExecutiveSession] = {}

    async def find_by_username(self, username: str) -> Executive | None:
        return self.executives.get(username.lower())

    async def add_session(self, session: ExecutiveSession) -> None:
        self.sessions[session.token_hash] = session

    async def find_session(self, token_hash: str) -> tuple[ExecutiveSession, Executive] | None:
        session = self.sessions.get(token_hash)
        if session is None:
            return None
        executive = next(e for e in self.executives.values() if e.id == session.executive_id)
        return session, executive

    async def delete_session(self, token_hash: str) -> None:
        self.sessions.pop(token_hash, None)

    async def save(self) -> None:
        pass


def executive(password_hash: str, id: int = 1, username: str = "ana") -> Executive:
    return Executive(id=id, username=username, display_name="Ana Pérez", password_hash=password_hash,
                     failed_attempts=0, locked_until=None, active=True, connected=False)


def web_session(phase: WebPhase = WebPhase.bot, pending_question: str | None = None) -> WebSession:
    return WebSession(id=uuid.UUID("11111111-1111-1111-1111-111111111111"), phase=phase, contact_attempts=0,
                      pending_question=pending_question, connected=True,
                      last_message_at=datetime(2026, 10, 7, 12, tzinfo=UTC))


class FakeHub(ConnectionHub):
    """Reparte en memoria como el real, pero registra lo publicado en vez de usar pg_notify."""

    def __init__(self):
        super().__init__()
        self.published: list[Event] = []

    def _ensure_listener(self) -> None:
        pass

    async def publish(self, session: AsyncSession, event: Event) -> None:
        self.published.append(event)


def assigned_chat(id: int = 7, executive_id: int = 1) -> LiveChat:
    return LiveChat(id=id, web_session_id=web_session().id, status=LiveChatStatus.assigned, executive_id=executive_id,
                    customer_name="Ana", customer_contact="ana@correo.cl", pending_question="¿Cheque?",
                    executive_disconnected_at=None)


def service_account_info(key_pem: str) -> dict[str, str]:
    return {
        "client_email": "bot@proyecto.iam.gserviceaccount.com",
        "private_key": key_pem,
        "private_key_id": "kid-1",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
