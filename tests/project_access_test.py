from typing import cast
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.project_access import allowed_boards, board_of, is_enabled, scoped_jql


def compiled(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class Rows:
    def __init__(self, values: list):
        self.values = values

    def __iter__(self):
        return iter(self.values)


class AccessSession:
    def __init__(self, emails: set[str], boards: list[str]):
        self.emails = emails
        self.boards = boards
        self.statements: list = []

    async def scalar(self, statement):
        self.statements.append(statement)
        sql = compiled(statement)
        return next((1 for email in self.emails if f"'{email}'" in sql), None)

    async def scalars(self, statement):
        self.statements.append(statement)
        return Rows(self.boards)


@pytest.mark.anyio
async def test_is_enabled_compara_el_correo_en_minusculas_y_solo_activos():
    session = AccessSession({"luis.ramos@autofin.cl"}, [])

    assert await is_enabled(cast(AsyncSession, session), "Luis.Ramos@Autofin.cl") is True
    assert await is_enabled(cast(AsyncSession, session), "otro@autofin.cl") is False
    assert await is_enabled(cast(AsyncSession, session), None) is False
    sql = compiled(session.statements[0])
    assert "lower(project_collaborator.email)" in sql and "project_collaborator.active" in sql


@pytest.mark.anyio
async def test_allowed_boards_solo_activos_y_sin_cache():
    session = AccessSession(set(), ["DAIA", "SGC"])

    assert await allowed_boards(cast(AsyncSession, session)) == ["DAIA", "SGC"]
    assert await allowed_boards(cast(AsyncSession, session)) == ["DAIA", "SGC"]
    assert len(session.statements) == 2 and "jira_board.active" in compiled(session.statements[0])


def test_scoped_jql_acota_a_los_tableros_y_conserva_el_orden():
    assert scoped_jql('text ~ "pagaré" ORDER BY created DESC', ["DAIA", "SGC"]) == (
        'project in ("DAIA", "SGC") AND (text ~ "pagaré") ORDER BY created DESC')
    assert scoped_jql("", ["DAIA"]) == 'project in ("DAIA")'


@pytest.mark.parametrize("jql", ['text ~ x) OR (project = OTRO', "text ~ x) OR project = OTRO OR (x = y", "status = Done)"])
def test_scoped_jql_rechaza_un_jql_que_intenta_salir_del_parentesis(jql):
    assert scoped_jql(jql, ["DAIA"]) is None


def test_scoped_jql_sin_tableros_no_busca():
    assert scoped_jql("text ~ x", []) is None


def test_board_of_toma_el_proyecto_de_la_clave():
    assert board_of("daia-52") == "DAIA" and board_of("no es clave") is None
