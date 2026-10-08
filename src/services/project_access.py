"""Quién puede usar Jira y los EDR y sobre qué tableros: datos de negocio, sin caché."""
import re
from collections.abc import Callable
import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.jira_board import JiraBoard
from src.models.project_collaborator import ProjectCollaborator
from src.services.drive_client import build_drive_client
from src.services.edr import EdrDocument, EdrSaved, get_edr, load_edr_template, save_edr
from src.services.jira_client import JiraIssue, JiraIssueRef, build_jira_client
from src.services.property import get_int_property, get_str_property
from src.utils.exceptions.database import DatabaseUnavailableError

ISSUE_KEY = re.compile(r"^([A-Z][A-Z0-9_]+)-\d+$")
ORDER_BY = re.compile(r"\s+order\s+by\s+.*$", re.IGNORECASE | re.DOTALL)
JIRA_HTTP_TIMEOUT_SECONDS = 15
DRIVE_HTTP_TIMEOUT_SECONDS = 30

async def is_enabled(session: AsyncSession, email: str | None) -> bool:
    if not email:
        return False
    statement = select(ProjectCollaborator.id).where(
        func.lower(ProjectCollaborator.email) == email.strip().lower(), ProjectCollaborator.active)
    try:
        return await session.scalar(statement) is not None
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc

async def allowed_boards(session: AsyncSession) -> list[str]:
    try:
        return list(await session.scalars(select(JiraBoard.key).where(JiraBoard.active).order_by(JiraBoard.key)))
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError(str(exc)) from exc

def board_of(key: str) -> str | None:
    match = ISSUE_KEY.match(key.strip().upper())
    return match.group(1) if match else None

def balanced(jql: str) -> bool:
    depth = 0
    for char in jql:
        depth += {"(": 1, ")": -1}.get(char, 0)
        if depth < 0:
            return False
    return depth == 0

def scoped_jql(jql: str, boards: list[str]) -> str | None:
    """El JQL del modelo queda dentro de un paréntesis acotado a los tableros; uno que intente salir se rechaza."""
    if not boards:
        return None
    order = ORDER_BY.search(jql)
    core = jql[:order.start()].strip() if order else jql.strip()
    if not balanced(core):
        return None
    scope = "project in (" + ", ".join(f'"{board}"' for board in boards) + ")"
    scoped = f"{scope} AND ({core})" if core else scope
    return f"{scoped} {order.group(0).strip()}" if order else scoped

class ProjectGateway:
    """Acceso y Jira para las herramientas del área: cada llamada abre su sesión y su cliente, sin caché."""

    def __init__(self, session_factory: Callable[[], AsyncSession]):
        self._session_factory = session_factory

    async def is_enabled(self, email: str | None) -> bool:
        async with self._session_factory() as session:
            return await is_enabled(session, email)

    async def allowed_boards(self) -> list[str]:
        async with self._session_factory() as session:
            return await allowed_boards(session)

    async def search(self, jql: str) -> list[JiraIssueRef]:
        async with self._session_factory() as session, httpx.AsyncClient(timeout=JIRA_HTTP_TIMEOUT_SECONDS) as http:
            client = await build_jira_client(session, http)
            return await client.search(jql, await get_int_property(session, "jira_max_results", 20))

    async def get_issue(self, key: str) -> JiraIssue | None:
        async with self._session_factory() as session, httpx.AsyncClient(timeout=JIRA_HTTP_TIMEOUT_SECONDS) as http:
            return await (await build_jira_client(session, http)).get_issue(key)

    async def children(self, key: str) -> list[JiraIssueRef]:
        async with self._session_factory() as session, httpx.AsyncClient(timeout=JIRA_HTTP_TIMEOUT_SECONDS) as http:
            client = await build_jira_client(session, http)
            return await client.children(key, await get_int_property(session, "jira_max_results", 20))

    async def get_edr(self, conversation_id: str) -> EdrDocument | None:
        async with self._session_factory() as session:
            return await get_edr(session, conversation_id)

    async def save_edr(self, conversation_id: str, edr: EdrDocument, new: bool) -> EdrSaved:
        async with self._session_factory() as session, httpx.AsyncClient(timeout=DRIVE_HTTP_TIMEOUT_SECONDS) as http:
            drive = await build_drive_client(session, http)
            folder_id = await get_str_property(session, "edr_drive_folder_id")
            template = await load_edr_template(session)
            return await save_edr(session, conversation_id, edr, drive, folder_id, new, template)
