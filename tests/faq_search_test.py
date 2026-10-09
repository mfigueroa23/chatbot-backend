import pytest
from langchain_core.messages import ToolCall
from src.agents.llm import AreaInfo, Catalog, FaqHit, Subtask
from src.agents.sub_agent import run_sub_agent, run_tool
from src.agents.tools.faq_search import FAQ_SEARCH_TOOL, faq_search_tool
from src.agents.tools.registry import ToolContext
from src.models.business_area import AreaScope
from tests.fakes import FakeKnowledge, FakeSubAgentModel, answer, tool_call

SAC = AreaInfo(1, "Servicio al Cliente", "Pagos", "Eres SAC.", ("Pagos",))
CATALOG = Catalog(AreaScope.external, "Coordinador externo.", "Reglas.", (SAC,))
KNOWLEDGE = FakeKnowledge({1: [FaqHit(9, "Seguros", "¿Qué cubre la póliza de desgravamen?", "El saldo del crédito.")],
                           2: [FaqHit(20, "Créditos", "¿Requisitos?", "Cédula y liquidaciones.")]})


def search_call(query: str) -> ToolCall:
    return {"name": FAQ_SEARCH_TOOL, "args": {"consulta": query}, "id": "s1", "type": "tool_call"}


@pytest.mark.anyio
async def test_busca_solo_en_el_area_del_sub_agente():
    knowledge = FakeKnowledge(KNOWLEDGE.faqs)
    tool = faq_search_tool(1, knowledge, 5)

    result = await run_tool([tool], search_call("seguro del auto"), ToolContext())

    assert knowledge.area_searches == [(1, "seguro del auto", 5)]
    assert "póliza de desgravamen" in result and "Requisitos" not in result


@pytest.mark.anyio
async def test_sin_resultados_lo_dice():
    assert await run_tool([faq_search_tool(7, FakeKnowledge(), 5)], search_call("x"), ToolContext()) == \
        "No se encontraron preguntas frecuentes."


@pytest.mark.anyio
async def test_busca_de_nuevo_y_luego_responde_con_lo_encontrado():
    query = "qué seguro tiene mi auto"
    model = FakeSubAgentModel({query: [tool_call(FAQ_SEARCH_TOOL, {"consulta": "póliza de desgravamen"}),
                                       answer(True, "La póliza de desgravamen cubre el saldo.")]})

    result = await run_sub_agent(model, CATALOG, SAC, [], Subtask(1, query), [faq_search_tool(1, KNOWLEDGE, 5)], 3, 5.0)

    assert result.found and "desgravamen" in result.content
    assert "póliza de desgravamen" in str(model.calls[1].messages[-1].content)


@pytest.mark.anyio
async def test_cada_busqueda_cuenta_en_el_tope_de_pasos():
    query = "seguro"
    model = FakeSubAgentModel({query: [tool_call(FAQ_SEARCH_TOOL, {"consulta": "otra"})]})

    result = await run_sub_agent(model, CATALOG, SAC, [], Subtask(1, query), [faq_search_tool(1, KNOWLEDGE, 5)], 2, 5.0)

    # Paso 1 busca; el paso 2 es el último y solo puede responder: el guion no responde → sin información.
    assert [call.answer_only for call in model.calls] == [False, True] and result.found is False
