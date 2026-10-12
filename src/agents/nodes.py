import logging
from langchain_core.messages import SystemMessage
from langgraph.graph import MessagesState
from langgraph.runtime import Runtime
from src.agents.context import AgentContext
from src.agents.tools.faq import search_faq

logger = logging.getLogger(__name__)

TOOLS = [search_faq]

async def assistant(state: MessagesState, runtime: Runtime[AgentContext]) -> dict:
  context = runtime.context
  llm = context.llm.bind_tools(TOOLS)
  response = await llm.ainvoke([SystemMessage(context.system_prompt), *state["messages"]])
  return { "messages": [response] }
