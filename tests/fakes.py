from datetime import datetime, timedelta
from typing import cast
from langchain_core.messages import BaseMessage
from sqlalchemy.ext.asyncio import AsyncSession
from src.agents.llm import AreaAnswer, AreaInfo, Classification, FaqHit
from src.utils.exceptions.mail import MailDeliveryError


class FakeClock:
    def __init__(self, now: datetime):
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


class PropertyRow:
    def __init__(self, key: str, value: str):
        self.key = key
        self.value = value


class PropertySession:
    def __init__(self, values: dict[str, str]):
        self.values = values

    async def execute(self, statement):
        return [PropertyRow(key, value) for key, value in self.values.items()]


def property_session(values: dict[str, str]) -> AsyncSession:
    return cast(AsyncSession, PropertySession(values))


class FakeAgentLLM:
    """Responde de forma fija y registra cada llamada para poder comprobarla en los tests."""

    def __init__(
        self,
        area_ids: list[int] | None = None,
        wants_human: bool = False,
        answers: dict[int, str | None] | None = None,
        combined: str = "respuesta combinada",
    ):
        self.classification = Classification(area_ids or [], wants_human)
        self.answers = answers or {}
        self.combined = combined
        self.calls: list[str] = []
        self.classified_areas: list[AreaInfo] = []
        self.histories: list[list[BaseMessage]] = []
        self.combined_parts: list[AreaAnswer] = []

    async def classify(self, prompt: str, question: str, areas: list[AreaInfo], history: list[BaseMessage]) -> Classification:
        self.calls.append("classify")
        self.classified_areas = areas
        self.histories.append(history)
        return self.classification

    async def answer(self, area: AreaInfo, question: str, faqs: list[FaqHit], history: list[BaseMessage]) -> AreaAnswer:
        self.calls.append("answer")
        return AreaAnswer(area.id, area.name, self.answers.get(area.id))

    async def combine(self, prompt: str, question: str, parts: list[AreaAnswer]) -> str:
        self.calls.append("combine")
        self.combined_parts = parts
        return self.combined


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
    def __init__(self, hits: dict[int, list[FaqHit]] | None = None):
        self.hits = hits or {}
        self.searched_area_ids: list[int] = []
        self.refreshed_area_ids: list[int] = []

    async def search(self, area_id: int, question: str) -> list[FaqHit]:
        self.searched_area_ids.append(area_id)
        return self.hits.get(area_id, [])

    async def refresh_stale_embeddings(self, area_ids: list[int]) -> None:
        self.refreshed_area_ids.extend(area_ids)


class FakeMailer:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.sent: list[tuple[list[str], str, str]] = []

    async def send(self, to: list[str], subject: str, body: str) -> None:
        if self.fail:
            raise MailDeliveryError("SMTP caído")
        self.sent.append((to, subject, body))
