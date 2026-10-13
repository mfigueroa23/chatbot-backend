import logging
import psycopg
from fastapi import APIRouter, Request, Response, status
from langchain_core.messages import HumanMessage
from src.database.session import SessionDep
from src.utils.exceptions.database import DatabaseUnavailableError
from src.utils.exceptions.property import PropertyNotFoundError
from src.utils.exceptions.agents import AgentNotFoundError
from src.interfaces.chat import ChatRequest, ChatResponse
from src.agents.llm import LLM
from src.agents.context import CoordinatorContext
from src.services.agents import get_prompt, list_sub_agents

route = APIRouter(tags=['Chat'])
logger = logging.getLogger(__name__)

AUDIENCIA = "externo"
COORDINADOR = "Agente Externo"

@route.post("/chat", responses={ 500: { "model": ChatResponse }, 503: { "model": ChatResponse } })
async def chat(request: Request, response: Response, message: ChatRequest, session: SessionDep) -> ChatResponse:
  try:
    llm = await LLM.create(session)
    prompt = await get_prompt(session, COORDINADOR)
    sub_agents = await list_sub_agents(session, audiencia = AUDIENCIA)
    if not sub_agents:
      raise AgentNotFoundError(f"sub-agentes de la audiencia '{AUDIENCIA}'")
    result = await request.app.state.graph.ainvoke(
      { "messages": [HumanMessage(message.mensaje)] },
      config = { "configurable": { "thread_id": str(message.chat_id) } },
      context = CoordinatorContext(
        llm = llm.llm,
        system_prompt = prompt,
        embeddings = llm.embeddings,
        audiencia = AUDIENCIA,
        sub_agents = { sub_agent.area: sub_agent for sub_agent in sub_agents }
      )
    )
    return ChatResponse(respuesta = result["messages"][-1].text)
  except (PropertyNotFoundError, AgentNotFoundError) as exc:
    logger.error("Agente mal configurado: %s", exc)
    response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    return ChatResponse(respuesta="Servicio no disponible. Intente de nuevo más tarde")
  except (DatabaseUnavailableError, psycopg.OperationalError) as exc:
    logger.error("Base de datos no disponible: %s", exc)
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ChatResponse(respuesta="Servicio no disponible. Intente de nuevo más tarde")
  except Exception:
    logger.exception("Ha ocurrido un error al solicitar una respuesta")
    response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    return ChatResponse(respuesta="Servicio no disponible. Intente de nuevo más tarde")
