import httpx
import pytest
from src.services.jira.client import JiraClient, adf_to_text
from src.services.jira.scope import board_of, scoped_jql
from src.utils.exceptions.jira import JiraUnavailableError

ISSUE = {"key": "DAIA-52", "fields": {
    "summary": "Portal de pagos", "status": {"name": "En curso"}, "issuetype": {"name": "Epic"},
    "description": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Rediseño"}]}]},
    "assignee": {"displayName": "Ana"}, "reporter": None, "parent": None,
    "subtasks": [{"key": "DAIA-53", "fields": {"summary": "Login", "status": {"name": "Hecho"}}}]}}


def only_get(handler):
    def guarded(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET", f"El cliente intentó {request.method}"
        return handler(request)
    return httpx.MockTransport(guarded)


def client_with(handler) -> tuple[JiraClient, httpx.AsyncClient]:
    http = httpx.AsyncClient(transport=only_get(handler))
    return JiraClient(http, "https://autofin.atlassian.net/", "bot@autofin.cl", "token-secreto"), http


@pytest.mark.parametrize("jql, expected", [
    ('text ~ "pagaré"', 'project in ("DAIA", "OPS") AND (text ~ "pagaré")'),
    ("status = Done ORDER BY created DESC", 'project in ("DAIA", "OPS") AND (status = Done) ORDER BY created DESC'),
    ("", 'project in ("DAIA", "OPS")'),
    ('text ~ "x") OR (project = SECRETO', None),
])
def test_scope_acota_el_jql_a_los_tableros(jql, expected):
    assert scoped_jql(jql, ["DAIA", "OPS"]) == expected


def test_scope_sin_tableros_no_busca_y_board_of_valida_la_clave():
    assert scoped_jql("status = Done", []) is None
    assert board_of(" daia-52 ") == "DAIA" and board_of("no es clave") is None and board_of("DAIA-") is None


@pytest.mark.anyio
async def test_client_lee_un_ticket_con_rutas_v3_y_solo_get():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json=ISSUE)

    jira, http = client_with(handler)
    async with http:
        issue = await jira.get_issue("DAIA-52")

    assert seen == ["/rest/api/3/issue/DAIA-52"]
    assert issue is not None and (issue.status, issue.issue_type, issue.assignee) == ("En curso", "Epic", "Ana")
    assert issue.description == "Rediseño" and [ref.key for ref in issue.subtasks] == ["DAIA-53"]


@pytest.mark.anyio
async def test_client_404_es_none_y_5xx_o_timeout_es_jira_unavailable():
    jira, http = client_with(lambda request: httpx.Response(404))
    async with http:
        assert await jira.get_issue("DAIA-1") is None
    jira, http = client_with(lambda request: httpx.Response(503))
    async with http:
        with pytest.raises(JiraUnavailableError):
            await jira.search("project = DAIA", 5)

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("lento", request=request)

    jira, http = client_with(timeout)
    async with http:
        with pytest.raises(JiraUnavailableError):
            await jira.get_issue("DAIA-1")


@pytest.mark.anyio
async def test_client_busca_hijos_por_parent():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params["jql"])
        return httpx.Response(200, json={"issues": []})

    jira, http = client_with(handler)
    async with http:
        assert await jira.children("DAIA-52", 20) == []
    assert seen == ["parent = DAIA-52"]


def test_client_adf_aplana_listas_y_saltos():
    doc = {"type": "doc", "content": [{"type": "bulletList", "content": [
        {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Uno"}]}]},
        {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Dos"}]}]}]}]}

    assert adf_to_text(doc) == "- Uno\n- Dos"
