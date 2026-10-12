import logging
from fastapi import APIRouter, Response, status
from langchain_core.messages import HumanMessage
from src.database.session import SessionDep
from src.utils.exceptions.database import DatabaseUnavailableError
from src.utils.exceptions.property import PropertyNotFoundError
from src.utils.exceptions.agents import AgentNotFoundError
from src.interfaces.chat import ChatRequest, ChatResponse
from src.agents.llm import LLM
from src.agents.graph import graph
from src.services.agents import get_prompt
from src.agents.context import AgentContext

route = APIRouter(tags=['Chat'])
logger = logging.getLogger(__name__)

@route.post("/chat", responses={ 500: { "model": ChatResponse }, 503: { "model": ChatResponse } })
async def chat(response: Response, message: ChatRequest, session: SessionDep) -> ChatResponse:
  try:
    llm = await LLM.create(session)
    prompt = await get_prompt(session, "Coordinator Agent")
    result = await graph.ainvoke(
      { "messages": [HumanMessage(message.mensaje)] },
      config = { "configurable": { "thread_id": message.chat_id } },
      context = AgentContext(llm = llm.llm, system_prompt = prompt)
    )
    return ChatResponse(respuesta = result["messages"][-1].text)
  except (PropertyNotFoundError, AgentNotFoundError) as exc:
    logger.error("Agente mal configurado: %s", exc)
    response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    return ChatResponse(respuesta="Servicio no disponible. Intente de nuevo más tarde")
  except DatabaseUnavailableError as exc:
    logger.error("Base de datos no disponible: %s", exc)
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ChatResponse(respuesta="Servicio no disponible. Intente de nuevo más tarde")
  except Exception:
    logger.exception("Ha ocurrido un error al solicitar una respuesta")
    response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    return ChatResponse(respuesta="Servicio no disponible. Intente de nuevo más tarde")
