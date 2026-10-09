import logging
import pytest
from langchain_core.messages import ToolCall
from pydantic import BaseModel
from src.agents.sub_agent import TOOL_FAILED, run_tool
from src.agents.tools.available import TOOLS
from src.agents.tools.registry import ToolContext, code_tool, tools_for


class NoArgs(BaseModel):
    pass


class Rut(BaseModel):
    rut: str


async def ok(args: NoArgs, context: ToolContext) -> str:
    return "ok"


async def who(args: Rut, context: ToolContext) -> str:
    return f"{context.requester} consultó {args.rut}"


REGISTRY = {name: code_tool(name, f"Herramienta {name}", NoArgs, ok) for name in ("tasa_del_dia", "estado_pedido")}
WHO = code_tool("quien", "Quién consulta", Rut, who)


def call(args: dict) -> ToolCall:
    return {"name": "quien", "args": args, "id": "1", "type": "tool_call"}


def test_entrega_solo_las_herramientas_asignadas_al_area():
    tools = tools_for("Servicio al Cliente", ["estado_pedido"], REGISTRY)

    assert [tool.name for tool in tools] == ["estado_pedido"]


def test_ignora_un_nombre_desconocido_con_un_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="src"):
        tools = tools_for("Ventas", ["tasa_del_dia", "no_existe"], REGISTRY)

    assert [tool.name for tool in tools] == ["tasa_del_dia"]
    assert "Ventas" in caplog.text and "no_existe" in caplog.text


def test_code_tool_arma_el_json_schema_desde_el_modelo():
    assert WHO.parameters["properties"]["rut"]["type"] == "string" and WHO.parameters["required"] == ["rut"]


@pytest.mark.anyio
async def test_run_recibe_el_contexto_con_el_correo_del_colaborador():
    result = await run_tool([WHO], call({"rut": "1-9"}), ToolContext(requester="ana@autofin.cl"))

    assert result == "ana@autofin.cl consultó 1-9"


@pytest.mark.anyio
async def test_argumentos_invalidos_dan_el_aviso_generico():
    assert await run_tool([WHO], call({"otro": 1}), ToolContext()) == TOOL_FAILED


def test_las_herramientas_registradas_tienen_nombre_unico():
    assert all(name == tool.name for name, tool in TOOLS.items())
