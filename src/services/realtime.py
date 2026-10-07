import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Literal
import asyncpg
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection
from src.config import settings
from src.utils.exceptions.database import DatabaseUnavailableError

logger = logging.getLogger(__name__)

EVENTS_CHANNEL = "chatbot_events"
LISTENER_RETRY_SECONDS = 5

EventKind = Literal["customer_message", "executive_message", "chat_taken", "executive_disconnected", "chat_closed"]
CUSTOMER_EVENTS = {"executive_message", "chat_taken", "executive_disconnected", "chat_closed"}
EXECUTIVE_EVENTS = {"customer_message", "chat_closed"}

@dataclass(frozen=True)
class Event:
    """Solo identificadores: el texto se lee de la BD al entregarlo (NOTIFY admite como mucho 8000 bytes)."""
    kind: EventKind
    chat_id: int
    web_session_id: str | None = None
    executive_id: int | None = None
    message_id: int | None = None
    reason: str | None = None

    def to_payload(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_payload(cls, payload: str) -> "Event":
        return cls(**json.loads(payload))

Deliver = Callable[[Event], Awaitable[None]]

class ConnectionHub:
    """Sockets conectados a este pod. Los eventos viajan entre pods con LISTEN/NOTIFY de PostgreSQL."""

    def __init__(self):
        self._customers: dict[str, Deliver] = {}
        self._executives: dict[int, Deliver] = {}
        self._listener: asyncio.Task[None] | None = None
        self._dispatching: set[asyncio.Task[None]] = set()

    def register_customer(self, web_session_id: str, deliver: Deliver) -> None:
        self._ensure_listener()
        self._customers[web_session_id] = deliver

    def unregister_customer(self, web_session_id: str) -> None:
        self._customers.pop(web_session_id, None)

    def register_executive(self, executive_id: int, deliver: Deliver) -> None:
        self._ensure_listener()
        self._executives[executive_id] = deliver

    def unregister_executive(self, executive_id: int) -> None:
        self._executives.pop(executive_id, None)

    async def publish(self, session: AsyncSession, event: Event) -> None:
        # pg_notify va en la transacción del cambio: el aviso solo sale si el commit se confirma.
        try:
            await session.execute(select(func.pg_notify(EVENTS_CHANNEL, event.to_payload())))
        except (SQLAlchemyError, OSError) as exc:
            raise DatabaseUnavailableError(str(exc)) from exc

    async def dispatch(self, payload: str) -> None:
        event = Event.from_payload(payload)
        targets: list[Deliver] = []
        if event.kind in CUSTOMER_EVENTS and event.web_session_id in self._customers:
            targets.append(self._customers[event.web_session_id])
        if event.kind in EXECUTIVE_EVENTS and event.executive_id in self._executives:
            targets.append(self._executives[event.executive_id])
        for deliver in targets:
            try:
                await deliver(event)
            except Exception:
                logger.exception("No se pudo entregar el evento %s del chat %s", event.kind, event.chat_id)

    async def close(self) -> None:
        if self._listener is not None:
            self._listener.cancel()

    def _ensure_listener(self) -> None:
        # Se arranca con el primer socket: un pod sin clientes no mantiene la conexión de escucha.
        if self._listener is None:
            self._listener = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        while True:
            try:
                connection = await asyncpg.connect(host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
                                                   password=settings.DB_PASSWORD, database=settings.DB_NAME)
                await connection.add_listener(EVENTS_CHANNEL, self._on_notify)
                logger.info("Escuchando eventos de chat en vivo en el canal %s", EVENTS_CHANNEL)
                while not connection.is_closed():
                    await asyncio.sleep(LISTENER_RETRY_SECONDS)
                logger.warning("Se cerró la conexión de escucha de eventos; se reconecta")
            except (OSError, asyncpg.PostgresError) as exc:
                logger.error("Listener de eventos no disponible (%s); se reintenta en %s s", exc, LISTENER_RETRY_SECONDS)
            await asyncio.sleep(LISTENER_RETRY_SECONDS)

    def _on_notify(self, connection: object, pid: int, channel: str, payload: object) -> None:
        task = asyncio.create_task(self.dispatch(str(payload)))
        self._dispatching.add(task)
        task.add_done_callback(self._dispatching.discard)

def get_hub(connection: HTTPConnection) -> ConnectionHub:
    return connection.app.state.hub
