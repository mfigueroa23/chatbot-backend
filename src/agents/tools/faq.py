from langchain.tools import ToolRuntime, tool
from src.agents.context import AgentContext
from src.database.session import SessionLocal
from src.services.faq import search_faqs

@tool(parse_docstring=True)
async def search_faq(query: str, runtime: ToolRuntime[AgentContext]) -> str:
  """Busca en las preguntas frecuentes oficiales del área asignada.

  Úsala siempre antes de responder cualquier consulta sobre Autofin.

  Args:
      query: La consulta del usuario como una pregunta completa y autocontenida en español.
  """
  context = runtime.context
  vector = await context.embeddings.aembed_query(query)
  async with SessionLocal() as session:
    faqs = await search_faqs(session, vector, area=context.area, audiencia=context.audiencia)
  if not faqs:
    return "No se encontraron preguntas frecuentes relacionadas con la consulta."
  return "\n\n---\n\n".join(f"[{faq.category}] {faq.question}\n{faq.answer}" for faq in faqs)
