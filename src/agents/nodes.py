import logging
from langchain_core.messages import SystemMessage
from langgraph.graph import MessagesState
from langgraph.runtime import Runtime
from src.agents.context import AgentContext

logger = logging.getLogger(__name__)

async def assistant(state: MessagesState, runtime: Runtime[AgentContext]) -> dict:
  context = runtime.context
  response = await context.llm.ainvoke([SystemMessage(context.system_prompt), *state['messages']])
  return { "messages": [response] }
