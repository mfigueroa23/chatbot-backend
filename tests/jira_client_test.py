import logging
import httpx
import pytest
from src.services.jira_client import JiraClient, JiraIssue, JiraIssueRef, adf_to_text
from src.utils.exceptions.jira import JiraUnavailableError

TOKEN = "token-secreto-de-jira"
ADF = {"type": "doc", "content": [
    {"type": "paragraph", "content": [{"type": "text", "text": "Automatizar el curse "}, {"type": "text", "text": "de créditos."}]},
    {"type": "bulletList", "content": [{"type": "listItem", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "Leer el pagaré"}]}]}]},
]}
EPIC = {"key": "DAIA-52", "fields": {"summary": "Curse automatizado", "status": {"name": "En curso"},
                                     "issuetype": {"name": "Epic"}, "description": ADF,
                                     "assignee": {"displayName": "Luis Ramos"}, "reporter": {"displayName": "Ana Pérez"},
                                     "subtasks": [{"key": "DAIA-53", "fields": {"summary": "RF-01", "status": {"name": "Hecho"}}}]}}


def client(requests: list[httpx.Request], routes: dict[str, httpx.Response]) -> JiraClient:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        for prefix, response in routes.items():
            if request.url.path.startswith(prefix):
                return response
        return httpx.Response(404)
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return JiraClient(http, "https://autofin.atlassian.net", "asistente@autofin.cl", TOKEN)


def test_adf_to_text_parrafos_y_listas():
    assert adf_to_text(ADF) == "Automatizar el curse de créditos.\n- Leer el pagaré"
    assert adf_to_text(None) == ""


@pytest.mark.anyio
async def test_get_issue_con_subtareas_y_descripcion():
    requests: list[httpx.Request] = []
    jira = client(requests, {"/rest/api/3/issue/DAIA-52": httpx.Response(200, json=EPIC)})

    issue = await jira.get_issue("DAIA-52")

    assert issue == JiraIssue("DAIA-52", "Curse automatizado", "En curso", "Epic",
                              "Automatizar el curse de créditos.\n- Leer el pagaré", "Luis Ramos", "Ana Pérez", None,
                              [JiraIssueRef("DAIA-53", "RF-01", "Hecho")])
    assert requests[0].headers["Authorization"].startswith("Basic ")


@pytest.mark.anyio
async def test_get_issue_inexistente_es_none():
    assert await client([], {"/rest/api/3/issue/": httpx.Response(404)}).get_issue("DAIA-999") is None


@pytest.mark.anyio
async def test_search_e_hijos_usan_jql():
    requests: list[httpx.Request] = []
    found = {"issues": [{"key": "DAIA-54", "fields": {"summary": "RF-02", "status": {"name": "Por hacer"}}}]}
    jira = client(requests, {"/rest/api/3/search/jql": httpx.Response(200, json=found)})

    results = await jira.search('project in ("DAIA") AND (text ~ "pagaré")', 20)
    children = await jira.children("DAIA-52", 20)

    assert results == children == [JiraIssueRef("DAIA-54", "RF-02", "Por hacer")]
    assert requests[0].url.params["jql"] == 'project in ("DAIA") AND (text ~ "pagaré")'
    assert requests[1].url.params["jql"] == "parent = DAIA-52" and requests[1].url.params["maxResults"] == "20"


@pytest.mark.anyio
async def test_solo_hace_peticiones_de_lectura():
    requests: list[httpx.Request] = []
    jira = client(requests, {"/rest/api/3/issue/": httpx.Response(200, json=EPIC),
                             "/rest/api/3/search/jql": httpx.Response(200, json={"issues": []})})

    await jira.get_issue("DAIA-52")
    await jira.search("text ~ x", 5)
    await jira.children("DAIA-52", 5)

    assert {request.method for request in requests} == {"GET"}
    assert not any(name.startswith(("create", "update", "delete", "transition", "comment")) for name in dir(jira))


@pytest.mark.anyio
@pytest.mark.parametrize("response", [httpx.Response(503), httpx.Response(401)])
async def test_jira_caido_lanza_no_disponible_sin_el_token_en_el_log(response, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG)

    with pytest.raises(JiraUnavailableError):
        await client([], {"/rest/api/3/issue/": response}).get_issue("DAIA-52")
    assert TOKEN not in caplog.text


@pytest.mark.anyio
async def test_jira_sin_conexion_lanza_no_disponible():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red")
    jira = JiraClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)), "https://x.atlassian.net", "a@b.cl", TOKEN)

    with pytest.raises(JiraUnavailableError):
        await jira.search("text ~ x", 5)
