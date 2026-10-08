"""Cliente de Jira de solo lectura: el asistente consulta tickets, nunca los crea ni los modifica."""
import base64
import logging
from dataclasses import dataclass, field
from typing import Any
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.property import get_str_property
from src.utils.exceptions.jira import JiraUnavailableError
from src.utils.exceptions.property import PropertyNotFoundError

logger = logging.getLogger(__name__)

ISSUE_FIELDS = "summary,status,issuetype,description,assignee,reporter,parent,subtasks"

@dataclass(frozen=True)
class JiraIssueRef:
    key: str
    summary: str
    status: str

@dataclass(frozen=True)
class JiraIssue:
    key: str
    summary: str
    status: str
    issue_type: str
    description: str
    assignee: str | None
    reporter: str | None
    parent: str | None
    subtasks: list[JiraIssueRef] = field(default_factory=list)

def adf_to_text(node: Any) -> str:
    # Las descripciones de Jira Cloud vienen en Atlassian Document Format: se aplanan a texto con viñetas.
    if not isinstance(node, dict):
        return ""
    kind = node.get("type")
    if kind == "text":
        return str(node.get("text", ""))
    if kind == "hardBreak":
        return "\n"
    children = [adf_to_text(child) for child in node.get("content", [])]
    if kind == "listItem":
        return "- " + "".join(children).strip()
    if kind in ("doc", "bulletList", "orderedList"):
        return "\n".join(child for child in children if child)
    return "".join(children)

def ref_of(item: dict[str, Any]) -> JiraIssueRef:
    fields = item.get("fields") or {}
    return JiraIssueRef(item["key"], fields.get("summary", ""), (fields.get("status") or {}).get("name", ""))

def name_of(person: dict[str, Any] | None) -> str | None:
    return person.get("displayName") if person else None

class JiraClient:
    def __init__(self, http: httpx.AsyncClient, base_url: str, email: str, api_token: str):
        self._http = http
        self._base_url = base_url.rstrip("/")
        credentials = base64.b64encode(f"{email}:{api_token}".encode()).decode()
        self._headers = {"Authorization": f"Basic {credentials}", "Accept": "application/json"}

    async def search(self, jql: str, max_results: int) -> list[JiraIssueRef]:
        body = await self._get("/rest/api/3/search/jql", jql=jql, maxResults=str(max_results), fields="summary,status")
        return [ref_of(item) for item in (body or {}).get("issues", [])]

    async def get_issue(self, key: str) -> JiraIssue | None:
        body = await self._get(f"/rest/api/3/issue/{key}", fields=ISSUE_FIELDS)
        if body is None:
            return None
        fields = body.get("fields") or {}
        parent = fields.get("parent")
        return JiraIssue(
            body["key"], fields.get("summary", ""), (fields.get("status") or {}).get("name", ""),
            (fields.get("issuetype") or {}).get("name", ""), adf_to_text(fields.get("description")),
            name_of(fields.get("assignee")), name_of(fields.get("reporter")), parent["key"] if parent else None,
            [ref_of(item) for item in fields.get("subtasks", [])])

    async def children(self, key: str, max_results: int) -> list[JiraIssueRef]:
        return await self.search(f"parent = {key}", max_results)

    async def _get(self, path: str, **params: str) -> dict[str, Any] | None:
        try:
            response = await self._http.get(f"{self._base_url}{path}", params=params, headers=self._headers)
        except httpx.HTTPError as exc:
            logger.error("Jira no respondió: %s", type(exc).__name__)
            raise JiraUnavailableError(type(exc).__name__) from exc
        if response.status_code == 404:
            return None
        if response.is_error:
            # Solo el código: la respuesta podría repetir datos de la petición.
            logger.error("Jira respondió %s en %s", response.status_code, path)
            raise JiraUnavailableError(str(response.status_code))
        return response.json()

async def build_jira_client(session: AsyncSession, http: httpx.AsyncClient) -> JiraClient:
    try:
        return JiraClient(http, await get_str_property(session, "jira_base_url"), await get_str_property(session, "jira_email"),
                          await get_str_property(session, "jira_api_token"))
    except PropertyNotFoundError as exc:
        logger.error("Jira no está configurado: falta la property %s", exc)
        raise JiraUnavailableError("sin configurar") from exc
