"""buscar_faq: el sub-agente vuelve a buscar en las FAQ de su propia área con otra redacción (spec 002, RF-25 a RF-27).
Nunca en otra área: el área queda fijada al construir la herramienta (RF-26)."""
from pydantic import BaseModel, Field
from src.agents.llm import KnowledgeSource
from src.agents.prompts import describe_faqs
from src.agents.tools.registry import AreaTool, ToolContext, code_tool

FAQ_SEARCH_TOOL = "buscar_faq"

class FaqQuery(BaseModel):
    consulta: str = Field(description="La consulta con otras palabras, sinónimos o más específica que la anterior")

def faq_search_tool(area_id: int, knowledge: KnowledgeSource, k: int) -> AreaTool:
    async def search(args: FaqQuery, context: ToolContext) -> str:
        return describe_faqs(await knowledge.search_area(area_id, args.consulta, k))
    return code_tool(
        FAQ_SEARCH_TOOL,
        "Busca de nuevo en las preguntas frecuentes de tu área con otra redacción, cuando las que recibiste no "
        "responden la consulta o la responden solo en parte.",
        FaqQuery, search)
