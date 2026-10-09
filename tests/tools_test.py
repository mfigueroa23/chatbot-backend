import logging
from pydantic import BaseModel
from src.agents.tools.registry import TOOLS, AreaTool, tools_for


class NoArgs(BaseModel):
    pass


async def ok(args: BaseModel) -> str:
    return "ok"


REGISTRY = {name: AreaTool(name, f"Herramienta {name}", NoArgs, ok) for name in ("tasa_del_dia", "estado_pedido")}


def test_entrega_solo_las_herramientas_asignadas_al_area():
    tools = tools_for("Servicio al Cliente", ["estado_pedido"], REGISTRY)

    assert [tool.name for tool in tools] == ["estado_pedido"]


def test_ignora_un_nombre_desconocido_con_un_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="src"):
        tools = tools_for("Ventas", ["tasa_del_dia", "no_existe"], REGISTRY)

    assert [tool.name for tool in tools] == ["tasa_del_dia"]
    assert "Ventas" in caplog.text and "no_existe" in caplog.text


def test_el_registro_de_la_2_0_0_esta_vacio():
    assert TOOLS == {} and tools_for("Ventas", []) == []
