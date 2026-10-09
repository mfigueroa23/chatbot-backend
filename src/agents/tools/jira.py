"""Herramientas de Jira del área Proyectos, en solo lectura (spec 002, RF-17 a RF-24). No hay ninguna herramienta que
cree, modifique, comente o transicione tickets: el «solo puedo consultar» (RF-21) lo dice el sub-agente."""
import logging
from collections.abc import Awaitable, Callable
import httpx
from pydantic import BaseModel, Field
from src.agents.prompts import information
from src.agents.tools.registry import AreaTool, ToolContext, code_tool
from src.services.jira.boards import allowed_boards
from src.services.jira.client import JiraClient, JiraIssue, JiraIssueRef
from src.services.jira.scope import board_of, scoped_jql
from src.utils.exceptions.database import DatabaseUnavailableError
from src.utils.exceptions.jira import JiraUnavailableError
from src.utils.exceptions.property import PropertyNotFoundError

logger = logging.getLogger(__name__)

NOT_FOUND = "No encuentro el ticket {key}."
JIRA_DOWN = "No pude consultar Jira en este momento."
INVALID_SEARCH = "No pude buscar con esa condición: escribe una condición JQL simple, sin indicar el proyecto."
NO_RESULTS = "No encontré tickets con esa búsqueda en los tableros permitidos."

BoardsLoader = Callable[[ToolContext], Awaitable[list[str]]]

class TicketKey(BaseModel):
    clave: str = Field(description="Clave del ticket o épica, por ejemplo DAIA-52")

class TicketSearch(BaseModel):
    jql: str = Field(description='Condición JQL sin indicar el proyecto, por ejemplo text ~ "pagaré" AND status != Done')

async def boards_from_db(context: ToolContext) -> list[str]:
    if context.session_factory is None:
        raise DatabaseUnavailableError("No hay fábrica de sesiones para leer los tableros")
    async with context.session_factory() as session:
        return await allowed_boards(session)

def describe_refs(refs: list[JiraIssueRef]) -> str:
    return "\n".join(f"- {ref.key} {ref.summary} ({ref.status})" for ref in refs)

def describe_issue(issue: JiraIssue, children: list[JiraIssueRef]) -> str:
    lines = [f"{issue.key} · {issue.summary} · {issue.status}",
             f"Tipo: {issue.issue_type} · Responsable: {issue.assignee or 'sin asignar'} · Informante: {issue.reporter or '—'}"]
    if issue.parent:
        lines.append(f"Pertenece a: {issue.parent}")
    lines.append(f"Descripción:\n{issue.description or '(sin descripción)'}")
    if issue.subtasks:
        lines.append(f"Subtareas:\n{describe_refs(issue.subtasks)}")
    if children:
        lines.append(f"Tickets hijos:\n{describe_refs(children)}")
    return "\n".join(lines)

def jira_tools(transport: httpx.AsyncBaseTransport | None = None,
               load_boards: BoardsLoader = boards_from_db) -> list[AreaTool]:
    """Las herramientas reciben el transporte HTTP y el lector de tableros para poder probarse sin red ni BD."""

    def client(context: ToolContext, http: httpx.AsyncClient) -> JiraClient:
        # Credenciales de la foto de properties del mensaje (plan 002, D15); nunca van al log.
        properties = context.properties
        return JiraClient(http, properties.required("jira_base_url"), properties.required("jira_email"),
                          properties.required("jira_api_token"))

    def http_client(context: ToolContext) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=context.properties.get_int("jira_timeout_seconds", 5), transport=transport)

    async def read_ticket(args: TicketKey, context: ToolContext) -> str:
        key = args.clave.strip().upper()
        board = board_of(key)
        try:
            # El tablero se revisa antes de llamar a Jira: no se revela si existe en otro (RF-19, plan D14).
            if board is None or board not in await load_boards(context):
                return NOT_FOUND.format(key=key)
            async with http_client(context) as http:
                jira = client(context, http)
                issue = await jira.get_issue(key)
                if issue is None:
                    return NOT_FOUND.format(key=key)
                children = await jira.children(key, context.properties.get_int("jira_max_results", 20))
        except PropertyNotFoundError as exc:
            logger.error("Jira no está configurado: falta la property %s", exc.key)
            return JIRA_DOWN
        except JiraUnavailableError:
            return JIRA_DOWN
        # La descripción la escribe cualquiera en Jira: es información, nunca instrucciones (RF-24).
        return information("ticket de Jira", describe_issue(issue, children))

    async def search_tickets(args: TicketSearch, context: ToolContext) -> str:
        try:
            jql = scoped_jql(args.jql, await load_boards(context))
            if jql is None:
                return INVALID_SEARCH
            async with http_client(context) as http:
                refs = await client(context, http).search(jql, context.properties.get_int("jira_max_results", 20))
        except PropertyNotFoundError as exc:
            logger.error("Jira no está configurado: falta la property %s", exc.key)
            return JIRA_DOWN
        except JiraUnavailableError as exc:
            # Un JQL mal formado responde 400: se trata como búsqueda inválida, sin detalle.
            return INVALID_SEARCH if str(exc) == "400" else JIRA_DOWN
        return information("búsqueda en Jira", describe_refs(refs)) if refs else NO_RESULTS

    return [
        code_tool("leer_ticket", "Lee un ticket o una épica de Jira: estado, tipo, responsable, descripción, "
                  "subtareas y tickets hijos.", TicketKey, read_ticket),
        code_tool("buscar_tickets", "Busca tickets de Jira con una condición JQL, sin indicar el proyecto: la "
                  "búsqueda se acota sola a los tableros permitidos.", TicketSearch, search_tickets),
    ]
