import uuid
from datetime import UTC, datetime, timedelta
from typing import cast
from langchain_core.messages import BaseMessage
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.llm import AgentReply, FaqHit
from src.agents.retriever import Knowledge, ProcedureHit
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


class FakeAgentLLM:
    """Devuelve respuestas estructuradas guionizadas (una por mensaje) y cuenta las llamadas al modelo."""

    def __init__(self, *replies: AgentReply):
        self.replies = list(replies) or [AgentReply("no_answer", "")]
        self.calls = 0
        self.messages: list[list[BaseMessage]] = []

    async def respond(self, messages: list[BaseMessage]) -> AgentReply:
        self.calls += 1
        self.messages.append(list(messages))
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
                 other_scope_match: bool = False, stored: list[ProcedureHit] | None = None):
        self.faqs = faqs or []
        self.procedures = procedures or []
        # Procedimientos que existen en la BD aunque la búsqueda de este mensaje no los devuelva.
        self.stored = (stored or []) + self.procedures
        self.other_scope_match = other_scope_match
        self.searches: list[tuple[AreaScope, str]] = []
        self.refreshed_area_ids: list[int] = []

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
