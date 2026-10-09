from pydantic import BaseModel
from src.agents.llm import AreaInfo
from src.agents.tools.access import can_use_tools, restricted_note
from src.agents.tools.registry import ToolContext, code_tool

OPEN = AreaInfo(1, "Servicio al Cliente", "Pagos", "", members=None)
PROJECTS = AreaInfo(3, "Proyectos", "Jira y EDR", "", members=frozenset({"jp@autofin.cl"}))


class Clave(BaseModel):
    clave: str


async def read(args: Clave, context: ToolContext) -> str:
    return "ok"


JIRA = code_tool("leer_ticket", "Lee un ticket de Jira: estado y subtareas.", Clave, read)


def test_area_sin_lista_ofrece_sus_herramientas_a_todos_incluso_anonimos():
    assert can_use_tools(OPEN, "cualquiera@autofin.cl") and can_use_tools(OPEN, None)


def test_area_con_lista_solo_a_los_habilitados_sin_distinguir_mayusculas():
    assert can_use_tools(PROJECTS, "JP@Autofin.cl ")
    assert not can_use_tools(PROJECTS, "otro@autofin.cl")


def test_un_anonimo_nunca_usa_las_herramientas_de_un_area_con_lista():
    assert not can_use_tools(PROJECTS, None) and not can_use_tools(PROJECTS, "  ")


def test_la_nota_describe_las_funciones_sin_nombrar_la_herramienta():
    note = restricted_note([JIRA])

    assert "Lee un ticket de Jira" in note and "no está habilitada" in note
    assert "leer_ticket" not in note and "preguntas frecuentes" in note
