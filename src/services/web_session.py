import re
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.web_session import WebPhase, WebSession
from src.utils.clock import Clock
from src.utils.exceptions.database import DatabaseUnavailableError

MAX_CONTACT_ATTEMPTS = 3
# Un socket sin heartbeat en este plazo cuenta como desconectado, aunque su pod haya muerto sin avisar.
HEARTBEAT_TIMEOUT = timedelta(seconds=90)
WEB_ADMISSION_LOCK_ID = 727_100_002
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_PATTERN = re.compile(r"^\+?[\d\s-]+$")

@dataclass(frozen=True)
class ContactResult:
    outcome: Literal["queued", "retry", "exhausted"]
    name: str = ""
    contact: str = ""

def start_offer(web_session: WebSession, question: str) -> None:
    web_session.phase = WebPhase.offering_human
    web_session.pending_question = question

def answer_offer(web_session: WebSession, accept: bool) -> None:
    if accept:
        web_session.phase = WebPhase.collecting_contact
        web_session.contact_attempts = 0
    else:
        reset_to_bot(web_session)

def reset_to_bot(web_session: WebSession) -> None:
    web_session.phase = WebPhase.bot
    web_session.pending_question = None

def is_valid_phone(phone: str) -> bool:
    return bool(PHONE_PATTERN.match(phone)) and 8 <= sum(char.isdigit() for char in phone) <= 15

def submit_contact(web_session: WebSession, name: str, email: str | None, phone: str | None) -> ContactResult:
    name, email, phone = name.strip(), (email or "").strip(), (phone or "").strip()
    valid = (
        bool(name)
        and bool(email or phone)
        and (not email or bool(EMAIL_PATTERN.match(email)))
        and (not phone or is_valid_phone(phone))
    )
    if valid:
        web_session.phase = WebPhase.queued
        return ContactResult("queued", name, " / ".join(value for value in (email, phone) if value))
    web_session.contact_attempts += 1
    if web_session.contact_attempts >= MAX_CONTACT_ATTEMPTS:
        reset_to_bot(web_session)
        return ContactResult("exhausted")
    return ContactResult("retry")

def touch_last_message(web_session: WebSession, clock: Clock) -> None:
    web_session.last_message_at = clock.now()

async def get_web_session(session: AsyncSession, session_id: uuid.UUID) -> WebSession | None:
    try:
        return await session.get(WebSession, session_id)
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc

async def get_or_create(session: AsyncSession, clock: Clock, session_id: uuid.UUID | None, retention_days: int) -> WebSession:
    now = clock.now()
    try:
        if session_id is not None:
            existing = await session.get(WebSession, session_id)
            if existing is not None and existing.last_message_at > now - timedelta(days=retention_days):
                return existing
        # Inexistente o caducada: sesión nueva sin contexto. El barrido borra la caducada y su hilo del checkpointer.
        web_session = WebSession(id=uuid.uuid4(), phase=WebPhase.bot, contact_attempts=0, connected=False, last_message_at=now)
        session.add(web_session)
        await session.commit()
        return web_session
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc

async def admit(session: AsyncSession, clock: Clock, session_id: uuid.UUID, max_sessions: int) -> bool:
    now = clock.now()
    try:
        # El lock de transacción serializa las admisiones entre pods: dos conexiones a la vez no superan el límite.
        await session.execute(select(func.pg_advisory_xact_lock(WEB_ADMISSION_LOCK_ID)))
        connected = await session.scalar(
            select(func.count()).select_from(WebSession).where(
                WebSession.connected,
                WebSession.last_seen_at > now - HEARTBEAT_TIMEOUT,
                WebSession.id != session_id,
            )
        )
        if (connected or 0) >= max_sessions:
            await session.rollback()
            return False
        await session.execute(update(WebSession).where(WebSession.id == session_id).values(connected=True, last_seen_at=now))
        await session.commit()
        return True
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc

async def heartbeat(session: AsyncSession, clock: Clock, session_id: uuid.UUID) -> None:
    await execute_and_commit(session, update(WebSession).where(WebSession.id == session_id).values(
        connected=True, last_seen_at=clock.now()))

async def mark_disconnected(session: AsyncSession, session_id: uuid.UUID) -> None:
    await execute_and_commit(session, update(WebSession).where(WebSession.id == session_id).values(connected=False))

async def execute_and_commit(session: AsyncSession, statement) -> None:
    try:
        await session.execute(statement)
        await session.commit()
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc
